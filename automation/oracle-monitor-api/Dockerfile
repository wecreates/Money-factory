FROM node:22-alpine
WORKDIR /app
COPY package.json ./
COPY store.mjs server.mjs ./
RUN mkdir -p /data
ENV PORT=8080
VOLUME ["/data"]
EXPOSE 8080
CMD ["npm","start"]
