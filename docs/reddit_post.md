# r/politicalscience 게시글 초안

수정 이력
- 2026-09-02 최초 작성
- 2026-09-03 편향 보정 1·2단계 반영. 방법 설명을 다시 썼다.

**게시 전에 채울 것**: 아래 `[ ]` 로 표시한 숫자는 운영 DB 기준으로 채운다.
`GET /api/stats` 와 `PYTHONPATH=backend python backend/scripts/evidence_report.py`
로 확인한다. 채우지 않은 채로 올리면 안 된다.

---

**Title**

> Open-source relational map of South Korea's 22nd National Assembly — inferring inter-legislator conflict from news text, with an evidence log you can audit. Looking for methodological critique.

**Body**

I've been building a public dashboard that treats the sitting members of South Korea's National Assembly as a graph, and infers edges between them from Korean-language news coverage rather than from roll-call votes. It's live and open source.

I posted an earlier version of this here and got a fair beating on one point: the graph inherited whatever slant and sensationalism the source outlets had, and nothing in the pipeline controlled for it. I spent the last few days rebuilding the inference layer around that criticism. This post describes what changed and where it's still weak.

**Live board:** https://korea-politician.vercel.app
**Source:** https://github.com/showjihyun/KoreaPolitician

---

**What the graph contains right now**

- [ ] Member nodes, [ ] Party nodes
- [ ] party-affiliation edges
- [ ] sentiment edges ([ ] conflict, [ ] alliance)
- [ ] co-mention edges

---

**The thing I got wrong before**

Previously an edge was written per article. The storage layer merged edge properties by key, so the last article about a pair silently overwrote every earlier one. The edge carried one article's URL and score and nothing else — no article count, no outlet, no history. That made every aggregate-based correction impossible to even compute, and it meant the visible "conflict score" was just whatever the most recently crawled article said.

Everything below depends on fixing that first. Article-level judgements now go to an append-only observation log, and edges are written only as an aggregate over that log.

**How edges are derived now**

1. **Extraction.** For each pair of legislators named in the same sentence, a zero-shot NLI model is asked four directional hypotheses over a three-sentence window: A opposed B, A supported B, and the two reverses. The article-level score is the weighted mean of the top three windows rather than the single maximum.

2. **Attribution.** Each judgement records whether its evidence sentence is a direct quote, an indirect quote, or the reporter's own wording, and whether it is hedged. These are weighted 1.0 / 0.7 / 0.3, halved when hedged. The point is that "legislator A said X about B" and "the reporter framed A and B as opponents" are different kinds of evidence, and Korean papers are documented to select and re-frame politicians' statements to fit their own editorial line.

3. **Event de-duplication.** Wire copy is one editorial decision republished many times, and a single wire agency supplies most of the volume on the Korean news portals. Near-duplicate articles about the same pair within a day are collapsed into one event by SimHash over the article body, plus an exact normalized-headline rule. One event, one vote. Copy count feeds the attention score only.

4. **Cross-camp corroboration.** Outlets are mapped to conservative / centre-wire / progressive. Confidence treats each camp as a noisy observer: it rises with the number of independent events inside a camp but is capped, so a single camp cannot reach the confidence that two camps reporting independently can. Crucially, a cluster that spans camps is folded to "wire" rather than counted for each camp — otherwise syndication would make every relation look corroborated.

5. **Time.** Relations keep two numbers: a half-life-weighted recent tone (45 days) and an undecayed cumulative tone, alongside first-seen, last-seen and event count.

**What the display does with that**

Line thickness follows the corroborated weight. Relations reported by only one camp are drawn dashed. Arrows are drawn only when the evidence points one way; mutual exchanges get no arrow. Hovering a line shows the event count, article count, per-camp event counts, the direction, the evidence type, the confidence, the observation window and the evidence sentence itself.

**You can audit it**

`GET /api/relations/evidence` dumps the raw observation log with source article URLs, no authentication. Passing a pair returns the aggregate, every article behind it, and which articles were folded into the same event. `GET /api/relations/camps` publishes the outlet-to-camp table, because that mapping is a contestable judgement and hiding it would be the wrong move.

---

**Two different time bases, deliberately**

This is unchanged from my earlier post and I still want feedback on it.

- **Relations are cumulative.** An observation is never deleted. But the displayed strength now weights recent evidence more heavily via the half-life, so a conflict that stopped being reported fades without disappearing from the record.
- **Attention is a 7-day rolling window.** News mentions plus log-normalized YouTube view counts.

Each panel carries its window as a visible label.

**Attention scoring**

YouTube views are log-compressed before being added to the news component, and an article naming many legislators contributes 1/sqrt(n) to each rather than a full count. That same 1/sqrt(n) factor now also down-weights relation evidence drawn from roundup articles.

---

**Two measurements that might interest this sub**

Both are from hand-written test articles, not a labelled corpus. They are diagnostics that changed my design, not benchmark results.

The original symmetric hypothesis — "in this context A and B are in a hostile or critical relationship" — scored 0.607 on a textbook one-sided attack sentence, below my 0.65 threshold, so the relation was discarded. The directional form "A criticized B" scored 0.956 on the same premise, and the reverse direction scored 0.093. A symmetric hypothesis asserts a *mutual* state that one-sided criticism does not entail. I think this was silently suppressing a large share of real conflicts.

Going directional raised recall and hurt precision: on an article naming five legislators, requiring only that both names appear somewhere in the window produced ten relations, six of them between people who said nothing to or about each other. Requiring both names in the same sentence, except when the window contains only those two, left four relations, all real.

---

**Where I know it's still weak**

- **No inter-coder reliability.** This was the biggest gap last time and it is still open. I built the tooling — stratified sampling by polarity and camp, and a scorer reporting Krippendorff's alpha plus per-polarity precision and recall — but no human has coded the sample yet. Until that exists, treat the sentiment edges as illustration.
- **The dataset is young.** Continuous collection started 2026-08-30. The cumulative relation set is weeks old, not years.
- **Still one portal.** Outlet-level slant is now controlled for, but source *selection* is not: everything comes from one Korean news portal's politics, economy and society sections. If that portal's aggregation is itself skewed, the camp balance inherits it.
- **The outlet-to-camp table is hand-made.** It is published, and unknown outlets fall to centre rather than being guessed, but it is a judgement call and it is doing real work in the confidence calculation. The principled version would estimate outlet slant from data, which needs far more volume than I have.
- **No non-news evidence of cooperation.** News covers conflict and ignores collaboration, so alliance edges are structurally scarce. The obvious fix is bill co-sponsorship, which is recorded independently of any editor's judgement. I wrote the collector but the National Assembly's open API requires a registration key I decided not to pursue, so that table is empty and the code path is inert. If someone knows a keyless route to Korean co-sponsorship data I would take it.
- **Reporter narration still counts.** The principled choice is to exclude the reporter's own framing from relation edges entirely and use it only to estimate outlet tone. At current volume that removes most edges, so it is down-weighted to 0.3 instead of dropped. The evidence type is recorded per observation, so this is reversible.
- **Coverage bias is still baked into attention.** An attention score derived from media volume measures coverage, not influence. A backbencher doing consequential committee work registers as nothing.

---

**What I'd like input on**

1. Is the noisy-observer confidence model defensible? Each camp gets reliability that grows with its independent event count but is capped below 1, combined across camps as a noisy-OR. The effect is that one camp writing twelve stories never reaches the confidence of two camps writing three each. I chose the cap by argument, not by calibration, and I do not have ground truth to calibrate against.
2. Folding cross-camp wire clusters to "centre" rather than crediting each camp is the single decision that keeps corroboration meaningful. It also throws away the fact that both camps chose to republish. Is that the right trade?
3. For the hand-coded validation: is n=200 stratified by polarity and camp enough to report, and is Krippendorff's alpha the right statistic when one label dominates?
4. Same question as last time, still unresolved: is media co-occurrence defensible at all as a complement to vote-based measures like W-NOMINATE, or is the coverage bias fatal?

Everything is MIT-licensed, the pipeline is in the repo, and the evidence endpoint means the extraction is inspectable per article rather than on my word.
