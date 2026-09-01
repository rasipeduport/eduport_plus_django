# ---- Stage 1: build the Vite bundle -------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Vite inlines import.meta.env.* at BUILD time, so these must be build args,
# not runtime env vars. Changing them requires a rebuild of this image.
ARG VITE_API_URL
ARG VITE_GOOGLE_OAUTH_CLIENT_ID
ARG VITE_HUB_URL
ARG VITE_LEARN_URL
ENV VITE_API_URL=$VITE_API_URL \
    VITE_GOOGLE_OAUTH_CLIENT_ID=$VITE_GOOGLE_OAUTH_CLIENT_ID \
    VITE_HUB_URL=$VITE_HUB_URL \
    VITE_LEARN_URL=$VITE_LEARN_URL

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- Stage 2: serve the static bundle ------------------------------------
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
