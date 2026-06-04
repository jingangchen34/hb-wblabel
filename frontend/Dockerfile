FROM docker.m.daocloud.io/library/node:16-bullseye as build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf \
    automake \
    g++ \
    libtool \
    make \
    nasm \
    python3 \
    yasm \
    && rm -rf /var/lib/apt/lists/*
RUN npm config set registry https://registry.npmmirror.com
RUN npm config set unsafe-perm true
COPY . .
RUN cd main && npm install
RUN cd main && npm run build
RUN cd image-tool && npm install
RUN cd image-tool && npm run build
RUN cd pc-tool && npm install
RUN cd pc-tool && npm run build
RUN cd text-tool && npm install
RUN cd text-tool && npm run build

FROM docker.m.daocloud.io/library/nginx:1.22
COPY --from=build /build/dist /usr/share/nginx/html
