import os
import re

# 1. system_health.py
syshealth = "src/sm_telemetry_monitor/system_health.py"
with open(syshealth, 'r') as f:
    text = f.read()

# Add _join_llm_latency_onto_backends
join_fn = """
def _join_llm_latency_onto_backends(backends: list[dict], health_raw: dict) -> None:
    lat = None
    if "llm_latency" in health_raw and isinstance(health_raw["llm_latency"], dict):
        lat = health_raw["llm_latency"]
    else:
        cfg = health_raw.get("config")
        if isinstance(cfg, dict) and "llm_latency" in cfg and isinstance(cfg["llm_latency"], dict):
            lat = cfg["llm_latency"]
    if not lat:
        return
    for b in backends:
        url = b.get("url")
        if not url:
            continue
        entry = lat.get(url) or lat.get(url.rstrip("/"))
        if not isinstance(entry, dict):
            continue
        b["latency"] = {
            "latency_sum_s": entry.get("latency_sum_s"),
            "latency_max_s": entry.get("latency_max_s"),
            "requests_total": entry.get("requests_total"),
            "requests_failed_total": entry.get("requests_failed_total"),
            "latency_last_ts": entry.get("latency_last_ts"),
        }
"""
text = text.replace('def _join_token_usage_onto_backends', join_fn + '\ndef _join_token_usage_onto_backends')

# Call _join_llm_latency_onto_backends
text = text.replace('_join_token_usage_onto_backends(backends, raw)\n    return {', '_join_token_usage_onto_backends(backends, raw)\n    _join_llm_latency_onto_backends(backends, raw)\n    return {')

# Add llm_latency in _gateway_config
gw_config_old = """    if "allow_unauthenticated_provider_keys" in cfg:
        out["allow_unauthenticated_provider_keys"] = cfg["allow_unauthenticated_provider_keys"]"""
gw_config_new = """    if "allow_unauthenticated_provider_keys" in cfg:
        out["allow_unauthenticated_provider_keys"] = cfg["allow_unauthenticated_provider_keys"]
    
    if "llm_latency" in cfg and isinstance(cfg["llm_latency"], dict):
        out["llm_latency"] = cfg["llm_latency"]
    elif "llm_latency" in raw and isinstance(raw["llm_latency"], dict):
        out["llm_latency"] = raw["llm_latency"]"""
text = text.replace(gw_config_old, gw_config_new)

# Add llm_latency in system_health_snapshot
snap_old = """    if "llm_token_usage" in raw and isinstance(raw.get("llm_token_usage"), dict):
        out["llm_token_usage"] = raw["llm_token_usage"]"""
snap_new = """    if "llm_token_usage" in raw and isinstance(raw.get("llm_token_usage"), dict):
        out["llm_token_usage"] = raw["llm_token_usage"]
    if "llm_latency" in raw and isinstance(raw.get("llm_latency"), dict):
        out["llm_latency"] = raw["llm_latency"]"""
text = text.replace(snap_old, snap_new)

with open(syshealth, 'w') as f:
    f.write(text)

# 2. doctor.py
doctor = "src/sm_telemetry_monitor/doctor.py"
with open(doctor, 'r') as f:
    text = f.read()

# Add has_llm_latency
chk_old = """    has_llm_token_usage = "llm_token_usage" in raw"""
chk_new = """    has_llm_token_usage = "llm_token_usage" in raw
    has_llm_latency = "llm_latency" in raw or ("llm_latency" in cfg if isinstance(cfg, dict) else False)"""
text = text.replace(chk_old, chk_new)

chk_ret_old = """        "has_llm_token_usage": has_llm_token_usage,"""
chk_ret_new = """        "has_llm_token_usage": has_llm_token_usage,
        "has_llm_latency": has_llm_latency,"""
text = text.replace(chk_ret_old, chk_ret_new)

fmt_old = """            if block.get("has_llm_token_usage"):
                bits.append("llm_token_usage")"""
fmt_new = """            if block.get("has_llm_token_usage"):
                bits.append("llm_token_usage")
            if block.get("has_llm_latency"):
                bits.append("llm_latency")"""
text = text.replace(fmt_old, fmt_new)

with open(doctor, 'w') as f:
    f.write(text)

# 3. dashboard.html
dash = "static/dashboard.html"
with open(dash, 'r') as f:
    text = f.read()

pool_lat_bits = """
function poolLatencyBits(b) {
  const bits = [];
  const lat = b?.latency;
  if (!lat || typeof lat !== "object") return bits;
  const sum = Number(lat.latency_sum_s);
  const total = Number(lat.requests_total);
  const max = Number(lat.latency_max_s);
  const failed = Number(lat.requests_failed_total);
  if (Number.isFinite(total) && total > 0 && Number.isFinite(sum)) {
    const avg = sum / total;
    let line = `latency avg ${avg.toFixed(2)}s`;
    if (Number.isFinite(max) && max > 0) line += ` · max ${max.toFixed(2)}s`;
    line += ` · ${total} req${total === 1 ? "" : "s"}`;
    if (Number.isFinite(failed) && failed > 0) line += ` (${failed} failed)`;
    bits.push(line);
  } else if (Number.isFinite(total) && total === 0) {
    bits.push("latency 0 requests");
  }
  return bits;
}
"""
text = text.replace('function poolTokenBits(b) {', pool_lat_bits + '\nfunction poolTokenBits(b) {')

fill_popover_old = """  const tokBits = poolTokenBits(b);
  const metaBits = [...descBits, ...tokBits];"""
fill_popover_new = """  const tokBits = poolTokenBits(b);
  const latBits = poolLatencyBits(b);
  const metaBits = [...descBits, ...tokBits, ...latBits];"""
text = text.replace(fill_popover_old, fill_popover_new)

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

