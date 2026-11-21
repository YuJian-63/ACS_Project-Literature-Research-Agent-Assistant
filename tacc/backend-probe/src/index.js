import paper from "./paper.pdf";

export default {
  async fetch(request) {
    const path = new URL(request.url).pathname;

    if (request.method === "GET" && path === "/health") {
      return Response.json({ ok: true, service: "lr-backend-probe" });
    }

    if (request.method === "POST" && path === "/search") {
      let body;
      try {
        body = await request.json();
      } catch {
        return Response.json({ error: "Expected JSON" }, { status: 400 });
      }
      if (typeof body?.query !== "string" || !body.query.trim()) {
        return Response.json({ error: "Expected a nonempty query" }, { status: 400 });
      }
      return Response.json({
        query: body.query,
        mock: true,
        results: [{
          id: "probe-paper",
          title: "TACC backend probe",
          pdf_url: "/paper.pdf",
          snippet: "Static fixture for testing HTTP access.",
        }],
      });
    }

    if (request.method === "GET" && path === "/paper.pdf") {
      return new Response(paper, {
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'inline; filename="probe-paper.pdf"',
        },
      });
    }

    return Response.json({ error: "Not found" }, { status: 404 });
  },
};
