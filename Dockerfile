FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    FLASK_DEBUG=0

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY traffic_agent_system/requirements.txt ./traffic_agent_system/requirements.txt
COPY DairV2X_SceneGraph_Validator/requirements.txt ./DairV2X_SceneGraph_Validator/requirements.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "DairV2X_SceneGraph_Validator/app.py"]
