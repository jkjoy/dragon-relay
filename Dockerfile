FROM docker.io/library/python:3.10-alpine3.20

WORKDIR /workdir

RUN pip3 install requests ark

RUN apk add redis

COPY . /workdir

ENTRYPOINT /workdir/update-list.sh