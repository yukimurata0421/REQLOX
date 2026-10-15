export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname !== env.PUBLIC_HOST) return new Response("Not found", { status: 404 });
    if (url.protocol !== "https:") {
      url.protocol = "https:";
      return Response.redirect(url.toString(), 308);
    }
    if (!["GET", "HEAD", "POST"].includes(request.method)) return new Response("Method not allowed", { status: 405 });
    const destination = new URL(url.pathname + url.search, env.ORIGIN);
    const headers = new Headers(request.headers);
    headers.delete("Host");
    headers.delete("Cookie");
    const upstream = new Request(destination, { method: request.method, headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body, redirect: "manual" });
    return fetch(upstream, { cf: { cacheTtl: 0, cacheEverything: false } });
  }
};
