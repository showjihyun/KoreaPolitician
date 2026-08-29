# API server image for the SYNDEO / Korea Politician backend.
#
# IMPORTANT: the build context is the REPOSITORY ROOT, not backend/.
# The member dataset (data/) and the politician photos (img/) live outside
# backend/, and docker-compose supplies them through bind mounts. A hosted
# deployment has no such mounts, so they are baked into the image here.
#
#   docker build -t korea-politician-api .
#   docker run -p 5000:5000 --env-file backend/.env korea-politician-api

FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary and Pillow ship manylinux wheels, so no compiler is needed.
COPY backend/requirements-api.txt /tmp/requirements-api.txt
RUN pip install --no-cache-dir -r /tmp/requirements-api.txt

# Application code: api/, core/, scripts/, static/ ...
COPY backend/ /app/

# backend/data/assembly_members_complete.json is an empty placeholder in git;
# the real 600 KB dataset is at the repository root. Overwrite it.
COPY data/assembly_members_complete.json /app/data/assembly_members_complete.json

# core/image_manager.py resolves <repo>/img and falls back to /img.
COPY img/ /img/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 5000

# Render, Koyeb, Fly and Cloud Run inject $PORT; default to 5000 locally.
CMD ["sh", "-c", "uvicorn api.turingdb_server:app --host 0.0.0.0 --port ${PORT:-5000}"]
