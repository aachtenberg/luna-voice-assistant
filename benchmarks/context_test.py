"""Does a heavy turn fit? Long history, then a big search result, at several context sizes.

The brain sends no num_ctx, so it gets the server's default, which is 4096 on a
16 GB card. Oversized on purpose: a fact sits in the oldest history message, and
the answer has to reach it.

    python context_test.py <ollama-url> <model>
"""
import json, os, sys, time, httpx
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "brain"))
from prompts import SYSTEM_PROMPT, TOOLS
from llm.base import convert_tools_to_openai

URL, MODEL = sys.argv[1], sys.argv[2]
tools = convert_tools_to_openai(TOOLS)
para = ("The Ottawa River runs about twelve hundred and seventy kilometres, forming much of the border between Ontario and Quebec "
        "before it joins the Saint Lawrence near Montreal. Spring freshet usually peaks in early May, when snowmelt from the upper "
        "basin arrives, and the dams along the river hold back only part of it, so low lying properties near Pembroke watch the gauges closely. ")
hist = [{"role": "user", "content": "Remember this for later: my neighbour's dog is called Biscuit."},
        {"role": "assistant", "content": "Got it, your neighbour's dog is called Biscuit."}]
for i in range(5):
    hist += [{"role": "user", "content": f"Tell me more about the river, part {i + 1}."}, {"role": "assistant", "content": para * 3}]
search = "\n".join(f"- River report {i}: {para}" for i in range(14))
msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + hist + [
    {"role": "user", "content": "What's the river level today, and what did I say my neighbour's dog is called?"},
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "Ottawa River level Pembroke"}}}]},
    {"role": "tool", "content": search}]

print(f"{'ctx':>6} {'prompt tok':>10} {'recalled':>8} {'first tok s':>11}")
for ctx in (4096, 8192, 16384):
    httpx.post(f"{URL}/api/generate", json={"model": MODEL, "keep_alive": 0}, timeout=60)
    time.sleep(3)
    start, first, text, last = time.time(), None, "", {}
    body = {"model": MODEL, "messages": msgs, "tools": tools, "stream": True, "think": False, "options": {"num_ctx": ctx}}
    with httpx.stream("POST", f"{URL}/api/chat", json=body, timeout=240) as response:
        for line in response.iter_lines():
            chunk = json.loads(line)
            token = chunk.get("message", {}).get("content", "")
            if token and first is None:
                first = time.time() - start
            text += token
            if chunk.get("done"):
                last = chunk
    load = last.get("load_duration", 0) / 1e9
    print(f"{ctx:>6} {last.get('prompt_eval_count'):>10} {str('biscuit' in text.lower()):>8} {(first or 0) - load:>11.2f}")
    print("       ", repr(text[:150]))
