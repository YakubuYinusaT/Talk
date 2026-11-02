"""Every outbound message is a notifications row."""

from sqlalchemy.orm import Session

from ..models import Notification

TEST_PREFIX = "+2349990"  # numbers reserved for typed test conversations (the /try page): a text to one is recorded, never sent


async def send_sms(db: Session, services, *, to: str, body: str, template: str, caller_id=None) -> Notification:
    note = Notification(caller_id=caller_id, channel="sms", template=template, to_number=to, body=body)
    db.add(note)
    db.flush()
    if to.startswith(TEST_PREFIX):
        note.status, note.provider_message_id = "mock_sent", None
        return note
    if not to.startswith("+234"):   # the text-message service reaches Nigerian numbers: a caller from abroad is never told that a text is on its way
        note.status, note.provider_message_id = "not_sent_abroad", None
        return note
    status, message_id = await services.sms.send(to, body)
    note.status, note.provider_message_id = status, message_id
    return note
