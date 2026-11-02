# The image for Talk. The web application, the four simulated provider systems and the stand-in models all run from this one image.
FROM python:3.11-slim

# ffmpeg converts a caller's recording to the 16 kHz sound that Muse Voice Transcribe reads, and prepares the voice for a streamed call. Talk still works without
# it, using a plainer conversion, but the sound is better with it.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
# The dependencies are installed from pyproject.toml, so that this file and the project can never disagree about what Talk needs.
RUN pip install --no-cache-dir .

EXPOSE 8000
# The application reports whether it is ready on /health, which docker uses to decide whether the container is well.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
# Talk must run as one process, because the hospitals made in the onboarding wizard and the streamed-call agent keep their state in it, so there is no --workers option.
CMD ["uvicorn", "sofa.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
