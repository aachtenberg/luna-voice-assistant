# Local models for Luna, November 2026

**In short:** `gemma4:12b` can do all of Luna's inference on one 16 GB card. It passed 360 of 360 turns, answered faster than a second, and admitted every tool failure instead of inventing a result. Two things have to change first: a brain bug that drops a model's second tool call, and the context size, which at 4096 can cut an answer off mid-sentence.

## Results

Tested on one RX 9070 XT (16 GB), Ollama 0.40.13, through the brain's real streaming loop with stubbed tools. 36 cases covering chat, every tool, follow-ups and six tool failures, 3 repetitions each, with the streaming fix below applied. First token is measured from the question to the first token of the answer, tool rounds included, and leaves out speech to text and text to speech.

| Model | Score | First token, median | p90 | VRAM | What went wrong |
|---|---|---|---|---|---|
| **gemma4:12b** | **108/108** | 0.62s | 0.89s | 9 GiB | Nothing. 360/360 over 10 repetitions, worst first token 1.87s |
| gemma4:e4b | 103/108 | 0.20s | 0.29s | 5 GiB | Said "PM" every time; once answered with raw `<\|tool_response>` |
| gpt-oss:20b | 105/108 | 0.90s | 2.71s | 12.5 GiB | Read its own reasoning out as the answer; looped on failed tools until the step limit |
| qwen3:14b | 102/108 | 0.59s | 0.97s | 9.5 GiB | Said "PM"; promised "let me try again" and didn't |

The scores flatter gpt-oss and qwen3. Both gave answers that passed the regexes but read badly: step-limit apologies after four failed calls, and promises to retry that nothing keeps. `gemma4:26b` wasn't tested, as it needs about 17.7 GB and doesn't fit one card.

These can't be compared with July's Groq scores (`gpt-oss-120b` 21/21). Those 21 cases weren't kept.

## The bug

After the first tool runs, `chat_stream` streams the next round and reads only text, so if the model asks for another tool there, the call is dropped and the answer comes back empty. A model that calls tools one at a time loses its second call. On the unfixed code, "turn off whichever lights are on" failed 3 of 3 with `gemma4:12b`: it listed the lights, turned none off and said nothing. With the fix, 3 of 3 passed. gpt-oss:20b calls tools one at a time, so it suffered most: 14 empty answers out of 105 turns without the fix, in an earlier version of this test.

## Context

The brain sends no `num_ctx`, so it gets Ollama's default, 4096 on a 16 GB card. A turn of 4,074 prompt tokens left almost no room, and the answer stopped mid-sentence. At 8192 the same turn finished, for about 0.5 GiB more VRAM, and 16384 cost almost nothing further. Set `OLLAMA_CONTEXT_LENGTH=8192` on the host. A normal heavy turn is about 1,900 tokens, so this is a safety margin, but the failure is silent.

## Reproduce

```bash
python model_bench.py http://<ollama>:<port> gemma4:12b 3 out.jsonl
python context_test.py http://<ollama>:<port> gemma4:12b
```

Tools are stubbed, so this doesn't prove real devices or real search results. `/api/ps` under-reports gemma models (1.1 GB for a 9 GiB load); read `mem_info_vram_used` from sysfs on the GPU host instead.
