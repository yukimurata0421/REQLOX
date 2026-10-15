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
    // Bypass the edge cache; cacheTtl: 0 still overrides origin instructions.
    const response = await fetch(upstream, { cache: "no-store" });
    const resultHeaders = new Headers(response.headers);
    const publicPaths = new Set(["/demo/", "/demo/public-demo.html", "/demo/public-demo.js",
      "/demo/public-demo.css", "/demo/public-demo.json"]);
    if (response.status === 200 && publicPaths.has(url.pathname)
        && ["GET", "HEAD"].includes(request.method)) {
      const policy = resultHeaders.get("Cache-Control") || "no-store";
      resultHeaders.set("Cache-Control", /(?:^|,)\s*no-transform\s*(?:,|$)/i.test(policy)
        ? policy : policy + ", no-transform");
    } else {
      resultHeaders.set("Cache-Control", "no-store, no-transform");
    }
    // Preserve the original body and CSP, including rejected private requests.
    return new Response(response.body, { status: response.status,
      statusText: response.statusText, headers: resultHeaders });
  }
};
