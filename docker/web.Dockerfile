FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY src/web ./src/web
# Web 助手朗读依赖仓库根 shared/voice（@hct/voice），构建镜像必须一并打入。
COPY shared ./shared
# HCT-498：所有 Web 构建只提供正式账号密码登录；不再编译开发身份入口。
# 「模型实验室」等研发入口仍默认在生产构建中隐藏（HCT-439）。
ARG VITE_SHOW_ADVANCED_LAB=false
ENV VITE_SHOW_ADVANCED_LAB=${VITE_SHOW_ADVANCED_LAB}
RUN npm run build:web

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/src/web/dist /usr/share/nginx/html
