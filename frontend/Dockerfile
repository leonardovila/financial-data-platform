# ────────────────────────────────────────────────────────
#  financial-data-etl  ·  Frontend image
#
#  Multi-stage:
#    Stage 1 (build):   npm install + vite build → dist/
#    Stage 2 (runtime): Nginx serves static files
#
#  Why Nginx and not "npm run preview"?
#    Nginx uses ~5MB RAM. A Node process uses ~50MB+.
#    For static files, a real web server is the correct tool.
#    In AWS, this entire container gets replaced by S3+CloudFront.
# ────────────────────────────────────────────────────────

# ── Stage 1: Build ────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Layer caching: dependencies first, code second
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build
COPY . .

# Build-time env vars for Vite (injected at compile time, not runtime)
ARG VITE_API_URL=http://localhost:8000
ARG VITE_WS_URL=ws://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_WS_URL=${VITE_WS_URL}

RUN npm run build

# ── Stage 2: Serve ────────────────────────────────────
FROM nginx:alpine AS runtime

# Custom nginx config for SPA routing
COPY --from=build /app/dist /usr/share/nginx/html/financial

EXPOSE 3000

# Inline nginx config (no external file needed)
RUN printf 'server {\n\
    listen 3000;\n\
    root /usr/share/nginx/html;\n\
    \n\
    location /financial/ {\n\
        try_files $uri $uri/ /financial/index.html;\n\
    }\n\
    \n\
    # Cache static assets aggressively\n\
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {\n\
        expires 1y;\n\
        add_header Cache-Control "public, immutable";\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf
