import re
dash = "static/dashboard.html"
with open(dash, 'r') as f:
    text = f.read()

pool_render_old = """      if (b.reserved) meta.push("reserved");

      const titleBits = [b.url, b.status, place, b.model, ...meta.filter(m => m !== place && m !== b.model)];"""
pool_render_new = """      if (b.reserved) meta.push("reserved");

      const lat = b.latency || H?.config?.llm_latency?.[url] || H?.config?.llm_latency?.[url.replace(/\\/$/, "")] || H?.llm_latency?.[url] || H?.llm_latency?.[url.replace(/\\/$/, "")];
      if (lat && typeof lat === "object") {
        const sum = Number(lat.latency_sum_s);
        const total = Number(lat.requests_total);
        const max = Number(lat.latency_max_s);
        if (Number.isFinite(total) && total > 0 && Number.isFinite(sum)) {
          const avg = sum / total;
          meta.push(`avg ${avg.toFixed(2)}s`);
          if (Number.isFinite(max) && max > 0) {
            meta.push(`max ${max.toFixed(2)}s`);
          }
        }
      }

      const titleBits = [b.url, b.status, place, b.model, ...meta.filter(m => m !== place && m !== b.model)];"""
text = text.replace(pool_render_old, pool_render_new)
with open(dash, 'w') as f:
    f.write(text)
