FROM python:3.12-slim

WORKDIR /srv
COPY traffic_gen.py .

USER nobody
ENTRYPOINT ["python", "-u", "traffic_gen.py"]
CMD ["normal"]
