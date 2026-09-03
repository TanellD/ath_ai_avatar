# Контекст сборки — services/frontend (общие контракты сюда не нужны:
# TypeScript-типы генерируются отдельно и коммитятся).

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

# ------------------------------------------------------------------ dev
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---------------------------------------------------------------- build
FROM deps AS build
COPY . .
# Vite подставляет VITE_* на этапе сборки — в рантайме их уже не поменять.
# Пересборка образа при смене адреса сервиса — цена статической раздачи.
ARG VITE_API_URL
ARG VITE_WS_URL
ARG VITE_SCENARIO_API_URL
ARG VITE_SIMLI_API_KEY
ARG VITE_SIMLI_FACE_ID
RUN npm run build

# ----------------------------------------------------------------- prod
FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
