ARG BUILD_FROM=ghcr.io/hassio-addons/base-python:17.0.0
FROM $BUILD_FROM

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY run.sh .
RUN chmod a+x run.sh

COPY lunarsensor.py .

CMD [ "/run.sh" ]
