"""Luna local-model benchmark: can this Ollama model run Luna?

Drives the brain's real streaming tool loop with the real prompt and tools, and
stubbed tools, so no device is touched. Local inference only: nothing here builds
a paid provider. Run it on a GPU nothing else needs, as it loads and unloads the
model. Read the fault-case answers too; the scoring is regexes, and they have been
wrong in both directions.

    python model_bench.py <ollama-url> <model> <reps> <out.jsonl> [case,case]

BRAIN points it at another copy of brain/, to compare a change.
"""
import contextlib, io, json, os, re, statistics, sys, time
import httpx
sys.path.insert(0, os.environ.get("BRAIN", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "brain")))
for k in ("GROQ_API_KEY", "ANTHROPIC_API_KEY"): os.environ.pop(k, None)
from llm.ollama import OllamaProvider
from prompts import SYSTEM_PROMPT, TOOLS

URL, MODEL, REPS, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
ONLY = set(sys.argv[5].split(",")) if len(sys.argv) > 5 else None

OK = {
 "get_weather": "Pembroke: now 4 degrees, overcast, wind 12 km/h. Today high 7, low 1. Tomorrow high 3, low -2, light snow. Sunrise 7:52, sunset 17:08.",
 "web_search": "- Maple Leafs beat Senators 4-2: Toronto won 4-2 at home on Thursday night.\n- Bitcoin price today: Bitcoin trades near 91,000 US dollars.",
 "query_prometheus": "cluster CPU usage: 23 percent",
 "query_timescaledb": "[('Spa', 37.5), ('Sauna', 62.0), ('Main-Cottage', 19.5)]",
 "mqtt_publish": "Published to test/luna",
 "set_timer": "Timer set.",
 "cancel_timer": "Timer cancelled.",
 "list_timers": "pasta: 12 minutes remaining",
 "control_light": "Done.",
 "list_lights": "Kitchen: on. Patio: off. Living room: off. Ethan's room: on at 40 percent.",
}
BLOCKED = ("Web search is unavailable right now (search engines are blocking requests: brave, duckduckgo). "
           "Do not search again; tell the user you can't look that up at the moment.")
REFUSE = r"couldn|could not|issue|can't|cannot|can not|unable|fail|trouble|problem|didn't|wasn't|not able|sorry|unavailable|down|error|isn't"
HIST_WEATHER = [{"role": "user", "content": "What's the weather like?"}, {"role": "assistant", "content": "It's 4 degrees and overcast right now."}]
HIST_TIMER = [{"role": "user", "content": "Set a pasta timer for twenty minutes."}, {"role": "assistant", "content": "I've set a pasta timer for 20 minutes."}]
HIST_LONG = []
for q, a in (("What's the capital of Norway?", "The capital of Norway is Oslo."), ("How far is the moon?", "About 384,000 kilometres away."),
             ("Who wrote Frankenstein?", "Mary Shelley wrote Frankenstein, published in 1818."), ("What's the boiling point of water?", "100 degrees Celsius at sea level."),
             ("Tell me about the Ottawa River.", "It runs about 1,270 kilometres, forms much of the border between Ontario and Quebec, and joins the Saint Lawrence near Montreal."),
             ("How warm was it yesterday?", "It reached about 8 degrees in the afternoon.")):
    HIST_LONG += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]

def has(*words):
    return lambda v: any(w in str(v).lower() for w in words)
def call(calls, tool, **checks):
    return [c for c in calls if c[0] == tool and all(fn(c[1].get(k, "")) for k, fn in checks.items())]

CASES = [
 # (id, kind, text, check(calls)->bool, options)
 ("chat-capital", "chat", "What's the capital of Australia?", lambda c: not c, dict(say="canberra")),
 ("chat-math", "chat", "What's seventeen times six?", lambda c: not c, dict(say=r"102|one hundred (and )?two")),
 ("chat-thanks", "chat", "Thanks Luna, that's all.", lambda c: not c, {}),
 ("chat-time", "chat", "What time is it?", lambda c: not c, {}),
 ("chat-units", "chat", "How many centimetres are in a foot?", lambda c: not c, dict(say=r"30|thirty")),
 ("wx-now", "tool", "What's the weather like?", lambda c: call(c, "get_weather"), dict(say="4|four")),
 ("wx-sunset", "tool", "When's sunset today?", lambda c: call(c, "get_weather"), dict(say=r"5|17|five")),
 ("wx-jacket", "tool", "Should I bring a jacket tomorrow?", lambda c: call(c, "get_weather"), {}),
 ("timer-set", "tool", "Set a timer for ten minutes.", lambda c: call(c, "set_timer", duration=has("10", "ten", "600")), {}),
 ("timer-named", "tool", "Set a pasta timer for eight minutes.", lambda c: call(c, "set_timer", duration=has("8", "eight", "480"), name=has("pasta")), {}),
 ("timer-cancel", "tool", "Cancel the pasta timer.", lambda c: call(c, "cancel_timer", name=has("pasta")), {}),
 ("timer-left", "tool", "How long is left on my timer?", lambda c: call(c, "list_timers"), dict(history=HIST_TIMER, say="12|twelve")),
 ("light-on", "tool", "Turn on the kitchen light.", lambda c: call(c, "control_light", name=has("kitchen"), action=has("on")), {}),
 ("light-dim", "tool", "Dim the living room to thirty percent.", lambda c: [x for x in call(c, "control_light", name=has("living")) if "30" in str(x[1])], {}),
 ("light-off", "tool", "Turn off the patio light.", lambda c: call(c, "control_light", name=has("patio"), action=has("off")), {}),
 ("light-soft", "tool", "Make Ethan's room soft white.", lambda c: call(c, "control_light", name=has("ethan"), action=has("soft", "warm")), {}),
 ("light-list", "tool", "Which lights are on?", lambda c: call(c, "list_lights"), dict(say="kitchen")),
 ("light-two", "tool", "Turn off the kitchen and the patio.", lambda c: call(c, "control_light", name=has("kitchen"), action=has("off")) and call(c, "control_light", name=has("patio"), action=has("off")), {}),
 ("sensor-spa", "tool", "How warm is the spa?", lambda c: call(c, "query_timescaledb", sql=has("spa")), dict(say=r"37|thirty.seven")),
 ("sensor-sauna", "tool", "What's the temperature in the sauna?", lambda c: call(c, "query_timescaledb", sql=has("sauna")), {}),
 ("sensor-all", "tool", "What are all the temperatures right now?", lambda c: call(c, "query_timescaledb", sql=has("esp_temperature")), {}),
 ("search-score", "tool", "Who won the Leafs game last night?", lambda c: call(c, "web_search"), dict(say="leafs|toronto|maple")),
 ("search-price", "tool", "What's the price of bitcoin today?", lambda c: call(c, "web_search"), {}),
 ("prom-cpu", "tool", "What's the CPU usage on the cluster?", lambda c: call(c, "query_prometheus"), {}),
 ("mqtt", "tool", "Publish the message hello to the topic test slash luna.", lambda c: call(c, "mqtt_publish", topic=has("test/luna"), payload=has("hello")), {}),
 ("chain-lights", "tool", "Turn off whichever lights are on.", lambda c: call(c, "list_lights") and call(c, "control_light", name=has("kitchen"), action=has("off")) and call(c, "control_light", name=has("ethan"), action=has("off")), {}),
 ("combo", "tool", "Set a five minute timer and turn on the patio light.", lambda c: call(c, "set_timer", duration=has("5", "five", "300")) and call(c, "control_light", name=has("patio"), action=has("on")), {}),
 ("hist-followup", "tool", "What about tomorrow?", lambda c: call(c, "get_weather"), dict(history=HIST_WEATHER)),
 ("hist-long", "tool", "Turn on the kitchen light.", lambda c: call(c, "control_light", name=has("kitchen"), action=has("on")), dict(history=HIST_LONG)),
 ("hist-forget", "chat", "Thanks, and what was the first thing I asked you?", lambda c: not c, dict(history=HIST_LONG, say="norway")),
 # Faults: the tool fails, and the honest answer is that it failed
 ("fault-light", "fault", "Turn on the kitchen light.", lambda c: call(c, "control_light"), dict(fault={"control_light": "Failed to control Kitchen Light: Timed out getting discovery response"}, say=REFUSE, deny=r"\b(is|are) (now )?on\b|(?<!be )turned on\b|i've turned|let me try again")),
 ("fault-search", "fault", "Who won the Leafs game last night?", lambda c: call(c, "web_search") and len(call(c, "web_search")) <= 2, dict(fault={"web_search": BLOCKED}, say=REFUSE, deny=r"\b\d+\s*(to|-)\s*\d+\b")),
 ("fault-sensor", "fault", "How warm is the spa?", lambda c: call(c, "query_timescaledb"), dict(fault={"query_timescaledb": "Database error: connection refused"}, say=REFUSE, deny=r"\d+(\.\d+)?\s*degrees")),
 ("fault-weather", "fault", "What's the weather like?", lambda c: call(c, "get_weather"), dict(fault={"get_weather": "Weather service unavailable"}, say=REFUSE, deny=r"\d+\s*degrees")),
 ("fault-timer", "fault", "Set a timer for ten minutes.", lambda c: call(c, "set_timer"), dict(fault={"set_timer": "Failed to set timer: service error"}, say=REFUSE, deny=r"i've set|timer (is )?set\b|(?<!n't )(?<!not )(?<!to )set a timer for")),
 ("fault-empty", "fault", "How long is left on my timer?", lambda c: call(c, "list_timers"), dict(history=HIST_TIMER, fault={"list_timers": "No active timers."}, deny=r"\d+ minutes|twenty|twelve")),
]
BAD_SPEECH = re.compile(r"<tool_call|</?function|\{\s*\"|```|\*\*|°|\bAM\b|\bPM\b|<\|", re.S)

def ps():
    for m in httpx.get(f"{URL}/api/ps", timeout=10).json().get("models", []):
        if m["name"] == MODEL: return m
    return {}

def turn(case):
    cid, kind, text, check, o = case
    calls = []
    def stub(name):
        def fn(**kw):
            calls.append((name, kw))
            return o.get("fault", {}).get(name, OK[name])
        return fn
    p = OllamaProvider(url=URL, model=MODEL, tool_registry={k: stub(k) for k in OK}, auto_model=False)
    out, first, log = [], None, io.StringIO()
    t0 = time.time(); err = None
    with contextlib.redirect_stdout(log):
        try:
            for tok in p.chat_stream(text, SYSTEM_PROMPT, TOOLS, list(o.get("history", []))):
                if first is None and tok.strip(): first = time.time() - t0
                out.append(tok)
        except Exception as e:
            err = type(e).__name__
    total = time.time() - t0
    answer = "".join(out).strip()
    r = dict(case=cid, kind=kind, tool_ok=bool(check(calls)), answer=answer, calls=[c[0] for c in calls],
             ttft=first, total=total, err=err, retries=log.getvalue().count("forcing") + log.getvalue().count("forced"),
             clean=not BAD_SPEECH.search(answer), said=True, denied=False, nonempty=bool(answer))
    if o.get("say"): r["said"] = bool(re.search(o["say"], answer, re.I))
    if o.get("deny"): r["denied"] = bool(re.search(o["deny"], answer, re.I))
    r["ok"] = r["tool_ok"] and r["said"] and not r["denied"] and r["clean"] and r["nonempty"] and not err
    return r

# Cold load, from nothing on the card
httpx.post(f"{URL}/api/generate", json={"model": MODEL, "keep_alive": 0}, timeout=60)
time.sleep(3)
t = time.time()
cold = httpx.post(f"{URL}/api/chat", json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": False, "think": False, "options": {"num_predict": 1}}, timeout=300).json()
info = {"model": MODEL, "cold_seconds": round(time.time() - t, 1), "load_seconds": round(cold.get("load_duration", 0) / 1e9, 1)}
m = ps()
info.update(size_gb=round(m.get("size", 0) / 1e9, 1), vram_gb=round(m.get("size_vram", 0) / 1e9, 1), context=m.get("context_length"))
# How much of the context a heavy turn takes: full prompt, tools and history
tools_oa = [t for t in TOOLS]
heavy = httpx.post(f"{URL}/api/chat", json={"model": MODEL, "stream": False, "think": False, "tools": tools_oa, "options": {"num_predict": 1},
    "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + HIST_LONG + [{"role": "user", "content": "Turn on the kitchen light."}]}, timeout=300).json()
info["heavy_prompt_tokens"] = heavy.get("prompt_eval_count")
print(json.dumps(info), flush=True)

cases = [c for c in CASES if not ONLY or c[0] in ONLY]
with open(OUT, "w") as f:
    f.write(json.dumps({"info": info}) + "\n")
    for rep in range(REPS):
        for c in cases:
            r = turn(c); r["rep"] = rep
            f.write(json.dumps(r) + "\n"); f.flush()
            if not r["ok"]:
                print(f"  x {r['case']:<14} tool={r['tool_ok']} said={r['said']} denied={r['denied']} clean={r['clean']} err={r['err']} calls={r['calls']} {r['answer'][:90]!r}", flush=True)
