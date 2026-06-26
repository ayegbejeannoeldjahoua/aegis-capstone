FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
# `npm install` (not `npm ci`) because the lock file in the repo has
# drifted from package.json across sessions, and `npm ci` refuses to
# proceed with an out-of-sync lock. `npm install` resolves whatever is
# missing and produces a working build.
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/99-aegis-config.sh
RUN chmod +x /docker-entrypoint.d/99-aegis-config.sh

EXPOSE 80
