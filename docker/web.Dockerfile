FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY src/web ./src/web
# 本地教学 Compose 档默认保留「开发演示」登录入口（与 compose 默认的
# ALLOW_DEV_ACTOR_HEADER=true 对齐）；正式部署请用 --build-arg 关闭，
# 「模型实验室」等研发入口默认在生产构建中隐藏（HCT-439）。
ARG VITE_SHOW_DEV_LOGIN=true
ARG VITE_SHOW_ADVANCED_LAB=false
ENV VITE_SHOW_DEV_LOGIN=${VITE_SHOW_DEV_LOGIN} \
    VITE_SHOW_ADVANCED_LAB=${VITE_SHOW_ADVANCED_LAB}
RUN npm run build:web

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/src/web/dist /usr/share/nginx/html
