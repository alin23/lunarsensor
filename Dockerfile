FROM python:3.11 as build

ENV HOST=::
ENV PORT=80
ENV SENSOR_DEBUG=0

WORKDIR /usr/src/app

COPY . .
RUN pip install --upgrade pip
RUN make install

FROM python:3.11-slim as runtime

ENV PORT=80
ENV HOST=::

WORKDIR /usr/src/app
COPY --from=build /usr/src/app .
COPY --from=build /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=build /usr/local/bin/uvicorn /usr/local/bin/uvicorn

CMD [ "sh", "-c", "uvicorn --host $HOST --port $PORT --reload lunarsensor:app" ]