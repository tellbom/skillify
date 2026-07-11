FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE=/api
ARG VITE_KEYCLOAK_REALM_URL
ARG VITE_KEYCLOAK_REALM
ARG VITE_KEYCLOAK_CLIENT_ID=skillify-web
ARG VITE_RBAC_BASE_URL
ARG VITE_RBAC_PROJECT=skillify

ENV VITE_API_BASE=$VITE_API_BASE \
    VITE_KEYCLOAK_REALM_URL=$VITE_KEYCLOAK_REALM_URL \
    VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM \
    VITE_KEYCLOAK_CLIENT_ID=$VITE_KEYCLOAK_CLIENT_ID \
    VITE_RBAC_BASE_URL=$VITE_RBAC_BASE_URL \
    VITE_RBAC_PROJECT=$VITE_RBAC_PROJECT

RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/nginx-health || exit 1
