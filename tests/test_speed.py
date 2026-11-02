"""Speed: the request is read while the understanding runs, the recording is trimmed of silence before it is sent to be transcribed, and the prompt cache of Meta is used."""

import asyncio
import subprocess
import sys

import pytest

from scripts import latency_report
from sofa import audio
from sofa.clients.llm import LLMClient
from sofa.db import init_db, make_engine, make_session_factory
from sofa.models import Call, CallTurn
from tests.support import CALLER, call


# ---- the recording ---------------------------------------------------------------------------------------------------


class Ffmpeg:
    """A stand-in for ffmpeg that remembers how it was run and returns whatever each test needs."""

    def __init__(self, trimmed: bytes, plain: bytes = b"P" * 20000, fail_on_trim: bool = False):
        self.trimmed, self.plain, self.fail_on_trim, self.commands = trimmed, plain, fail_on_trim, []

    def __call__(self, cmd, input=None, capture_output=True):
        self.commands.append(cmd)
        trim = "-af" in cmd
        if trim and self.fail_on_trim:
            return subprocess.CompletedProcess(cmd, 1, b"", b"No such filter: silenceremove")
        return subprocess.CompletedProcess(cmd, 0, self.trimmed if trim else self.plain, b"")


def test_the_recording_is_trimmed_at_both_ends_but_never_in_the_middle(monkeypatch):
    fake = Ffmpeg(trimmed=b"T" * 20000)
    monkeypatch.setattr(audio.subprocess, "run", fake)
    assert audio.to_16k_mono(b"recording") == b"T" * 20000
    chain = fake.commands[0][fake.commands[0].index("-af") + 1]
    assert chain.count("silenceremove") == 2 and chain.count("areverse") == 2 and "stop_periods" not in chain      # the start is trimmed first, and then the end, which is trimmed on the reversed sound
    assert fake.commands[0][-4:] == ["-ac", "1", "-f", "wav", "pipe:1"] or "pipe:1" in fake.commands[0]


def test_a_recording_that_trims_to_nothing_is_sent_as_it_came(monkeypatch):
    fake = Ffmpeg(trimmed=b"H" * 44)          # Only a header is left, because the recording was all silence or too short to trim safely.
    monkeypatch.setattr(audio.subprocess, "run", fake)
    assert audio.to_16k_mono(b"recording") == b"P" * 20000 and len(fake.commands) == 2 and "-af" not in fake.commands[1]


def test_an_ffmpeg_without_the_silence_filter_still_converts_the_recording(monkeypatch):
    fake = Ffmpeg(trimmed=b"", fail_on_trim=True)
    monkeypatch.setattr(audio.subprocess, "run", fake)
    assert audio.to_16k_mono(b"recording") == b"P" * 20000


def test_the_simulator_recordings_are_never_sent_to_ffmpeg(monkeypatch):
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ffmpeg must not run")))
    assert audio.to_16k_mono(b"MOCK[en]:hello") == b"MOCK[en]:hello"


# ---- the model's prompt cache -------------------------------------------------------------------------------------------


class FakeHttp:
    def __init__(self):
        self.payloads = []

    async def post(self, url, json):  # noqa: A002
        self.payloads.append(json)

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": '{"action": "x"}'}}]}

        return R()


def test_calls_to_meta_carry_a_stable_cache_key_and_other_providers_do_not():
    meta = LLMClient("https://api.meta.ai", "muse-spark-1.3", "k", "meta")
    meta.http = FakeHttp()
    asyncio.run(meta._chat("SYSTEM", "hello"))
    assert meta.http.payloads[0]["prompt_cache_key"] == "talk"
    other = LLMClient("https://llm.example", "m", "k", "openai")
    other.http = FakeHttp()
    asyncio.run(other._chat("SYSTEM", "hello"))
    assert "prompt_cache_key" not in other.http.payloads[0]


# ---- reading the request while the understanding runs --------------------------------------------------------------------


def test_the_request_is_read_once_and_alongside_the_understanding(client, happ, said):
    order = []
    llm = happ.state.svc.llm
    inner = llm.extract

    async def spy(model, system, transcript, alternatives=None, json_schema=None):
        kind = system.split("\n", 1)[0][:10]
        order.append(("start", kind))
        await asyncio.sleep(0.05)        # A model call takes time, so if the two calls ran one after the other the first would end before the second began.
        out = await inner(model, system, transcript, alternatives, json_schema)
        order.append(("end", kind))
        return out

    llm.extract = spy
    replies = call(client, ["Please help me find the nearest clinic for antenatal care in Surulere.", "No, thank you."])
    assert "Surulere Care Clinic" in replies[1]
    first_turn = [e for e in order if e[1] in ("UNDERSTAND", "ARGUMENTS")][:4]
    assert sorted(e[1] for e in first_turn if e[0] == "start") == ["ARGUMENTS", "UNDERSTAND"]
    assert [e[0] for e in first_turn[:2]] == ["start", "start"]            # Both calls were started before either of them finished.
    assert sum(1 for e in order if e == ("start", "ARGUMENTS")) == 1       # The request was also read once and not twice.


def test_an_answer_to_a_question_is_not_read_as_a_new_request(client, happ):
    kinds = []
    llm = happ.state.svc.llm
    inner = llm.extract

    async def spy(model, system, transcript, alternatives=None, json_schema=None):
        kinds.append((transcript, system.split("\n", 1)[0][:10]))
        return await inner(model, system, transcript, alternatives, json_schema)

    llm.extract = spy
    call(client, ["Hello, I would like to book an appointment in Surulere, please.", "The second one, please."])
    assert ("The second one, please.", "ARGUMENTS") not in kinds and ("Hello, I would like to book an appointment in Surulere, please.", "ARGUMENTS") in kinds


# ---- the database must not lock a call out ---------------------------------------------------------------------------------


def test_a_database_file_waits_its_turn_instead_of_failing(tmp_path):
    from sofa.db import BUSY_SECONDS, make_engine

    engine = make_engine(f"sqlite:///{tmp_path}/calls.db")
    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    engine.dispose()
    assert mode == "wal" and busy == BUSY_SECONDS * 1000 and BUSY_SECONDS >= 30


def test_a_write_that_has_to_wait_for_another_write_succeeds_instead_of_failing(tmp_path):
    import threading
    import time

    from sqlalchemy import text

    from sofa.db import make_engine

    engine = make_engine(f"sqlite:///{tmp_path}/calls.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (n INTEGER)"))
    started, done = threading.Event(), []

    def hold_the_lock():
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO t VALUES (1)"))      # A write begins and is held for a while, as a slow turn would hold it.
            started.set()
            time.sleep(1.5)

    holder = threading.Thread(target=hold_the_lock)
    holder.start()
    started.wait(5)
    with engine.begin() as conn:                              # Another request needs to write in the meantime, so it waits and then succeeds.
        conn.execute(text("INSERT INTO t VALUES (2)"))
        done.append(True)
    holder.join()
    assert done == [True]
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM t")).scalar()
    engine.dispose()
    assert count == 2


def test_the_recording_is_asked_for_a_few_times_but_not_for_many_seconds():
    import inspect

    from sofa.audio import fetch_recording

    d = inspect.signature(fetch_recording).parameters
    waits = sum(d["wait"].default * (n + 1) for n in range(d["attempts"].default - 1))
    assert waits <= 5      # A recording that never appears is given up on within a few seconds and not after half a minute.


# ---- the report of where the time goes ------------------------------------------------------------------------------------


def test_the_latency_report_shows_the_time_of_each_stage_and_never_a_number_or_a_word_said(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path}/calls.db"
    engine = make_engine(url)
    init_db(engine)
    with make_session_factory(engine)() as db:
        phone_call = Call(provider_session_id="timed", from_number=CALLER, to_number="+2348000009999")
        db.add(phone_call)
        db.flush()
        for seq, total in enumerate((1800, 3200, 9000), start=1):
            stages = {"audio_fetch": 200, "asr": 600, "understand_and_act": total - 1000, "tts": 200, "total": total}
            db.add(CallTurn(call_id=phone_call.id, seq=seq, transcript="Please help me find a clinic.", action_taken="health_say|template", latency_ms=stages))
        db.commit()
    engine.dispose()
    monkeypatch.setattr(sys, "argv", ["latency_report", "--db", url])
    latency_report.main()
    report = capsys.readouterr().out
    assert "3 timed turns in 1 calls" in report and "speech to text" in report and "TOTAL (server share)" in report
    assert CALLER not in report and "find a clinic" not in report


def test_the_latency_report_says_so_when_no_turn_has_been_timed(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path}/empty.db"
    engine = make_engine(url)
    init_db(engine)
    engine.dispose()
    monkeypatch.setattr(sys, "argv", ["latency_report", "--db", url])
    latency_report.main()
    assert "No timed turns were found." in capsys.readouterr().out
