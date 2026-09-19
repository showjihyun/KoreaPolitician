"""README 에 붙는 데모(docs/demo.gif) 를 배포된 화면에서 다시 찍는다.

    python scripts/record_demo.py                  # 녹화 → GIF 교체까지
    python scripts/record_demo.py --out /tmp/x.gif # 다른 곳에 떨어뜨려 먼저 확인
    python scripts/record_demo.py --keep-video     # 원본 webm 도 남긴다

필요한 것: playwright(chromium), ffmpeg. gifsicle 은 있으면 쓰고 없으면 건너뛴다
(없어도 GIF 는 나오지만 1.8배쯤 커진다). 파이썬 쪽은 `pip install playwright` 뒤에
`playwright install chromium`.

30초를 일곱 장면으로 나눠 돈다. 전체 관계망 -> 선을 읽는 법 -> 화제성 순위 ->
관계선 클릭 -> 근거 패널 -> 근거 기사 -> 한국어 전환. 자막은 영문과 국문을 함께
얹는다. README 가 두 벌이고 같은 그림을 쓰기 때문이다.

무료 인스턴스는 15분 놀면 잠든다. 잠들어 있으면 첫 화면이 뜨는 데 1분쯤 걸리므로
녹화는 데이터가 다 붙은 뒤에 시작하고, 그 앞부분은 뒤에서 잘라낸다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://korea-politician.vercel.app/"
W, H = 1440, 900
GIF_W, GIF_H = 800, 500

def pick_pair(site):
    """그날 근거가 가장 많은 호불호 관계를 고른다.

    예전에는 이름을 박아 뒀다(김민석·정청래). 관계는 매일 다시 집계되므로
    2026-09-19 녹화에서 그 대립선이 사라져 있었고, 스크립트는 같은 두 사람의
    언급선을 붙잡고 근거 패널을 기다리다 멈췄다. 근거 패널이 이 화면에서
    보여 줄 수 있는 것을 다 보여 주려면 관측이 많은 쌍이어야 한다.
    """
    api = env_api(site)
    with urllib.request.urlopen(f"{api}/graph/all?limit=300", timeout=180) as res:
        data = json.load(res)
    name = {n["id"]: (n.get("properties") or {}).get("name") for n in data["nodes"]}
    best = None
    for edge in data["relationships"]:
        if edge["type"] not in ("NEGATIVE_SENTIMENT", "POSITIVE_SENTIMENT"):
            continue
        props = edge.get("properties") or {}
        rank = (props.get("n_observations") or 0, props.get("camp_coverage") or 0)
        if best is None or rank > best[0]:
            best = (rank, edge["from"], edge["to"],
                    name.get(edge["from"]), name.get(edge["to"]))
    if best is None:
        return None
    log(f"[demo] 대상 쌍: {best[3]} - {best[4]} (관측 {best[0][0]}건, "
        f"진영 커버 {best[0][1]})")
    return {"aId": best[1], "bId": best[2]}


def env_api(site):
    """보드가 쓰는 API 주소. 배포 화면과 같은 곳을 본다."""
    return os.environ.get("DEMO_API_BASE",
                          "https://korea-politician-api.onrender.com/api")

# 그래프 인스턴스는 컴포넌트 ref 안에 있다. 파이버를 거슬러 올라가
# getPositions 를 가진 ref 를 찾아 window 에 걸어 둔다. 노드 좌표를 알아야
# 관계선 한가운데를 짚을 수 있다.
FIBER_HACK = """
() => {
  const el = document.querySelector('.canvas');
  if (!el) return 'no-canvas';
  const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
  if (!key) return 'no-fiber';
  let fiber = el[key], hops = 0;
  while (fiber && hops < 40) {
    let hook = fiber.memoizedState, i = 0;
    while (hook && i < 80) {
      const cur = hook.memoizedState;
      if (cur && typeof cur === 'object' && cur.current
          && typeof cur.current.getPositions === 'function') {
        window.__net = cur.current;
        return 'ok';
      }
      hook = hook.next; i++;
    }
    fiber = fiber.return; hops++;
  }
  return 'not-found';
}
"""

# 자막과 가짜 커서. 커서는 녹화 영상에 마우스가 찍히지 않아서 넣는다.
OVERLAY = """
() => {
  const css = document.createElement('style');
  css.textContent = `
    #demo-cap {
      position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%);
      z-index: 99999; pointer-events: none; opacity: 0;
      transition: opacity .35s ease;
      background: rgba(9,12,18,.92); border: 1px solid rgba(120,140,170,.28);
      border-radius: 10px; padding: 11px 20px 12px; text-align: center;
      box-shadow: 0 10px 34px rgba(0,0,0,.55); max-width: 900px;
    }
    #demo-cap .en {
      font: 600 17px/1.35 'IBM Plex Sans KR', system-ui, sans-serif;
      color: #f2f5fa; letter-spacing: -.1px; display: block;
    }
    #demo-cap .ko {
      font: 400 14px/1.4 'IBM Plex Sans KR', system-ui, sans-serif;
      color: #93a3ba; display: block; margin-top: 3px;
    }
    #demo-cur {
      position: fixed; z-index: 99998; width: 20px; height: 20px;
      margin: -10px 0 0 -10px; border-radius: 50%; pointer-events: none;
      border: 2px solid rgba(255,255,255,.95); background: rgba(255,255,255,.22);
      box-shadow: 0 0 0 1px rgba(0,0,0,.45), 0 2px 10px rgba(0,0,0,.5);
      opacity: 0; transition: left .55s cubic-bezier(.4,0,.2,1),
        top .55s cubic-bezier(.4,0,.2,1), opacity .25s ease,
        transform .18s ease, background .18s ease;
      left: 50%; top: 50%;
    }
    #demo-cur.tap { transform: scale(.62); background: rgba(255,214,102,.85); }
  `;
  document.head.appendChild(css);
  const cap = document.createElement('div');
  cap.id = 'demo-cap';
  cap.innerHTML = '<span class="en"></span><span class="ko"></span>';
  document.body.appendChild(cap);
  const cur = document.createElement('div');
  cur.id = 'demo-cur';
  document.body.appendChild(cur);
  window.__cap = (en, ko) => {
    const box = document.getElementById('demo-cap');
    if (en === null) { box.style.opacity = 0; return; }
    box.querySelector('.en').textContent = en;
    box.querySelector('.ko').textContent = ko || '';
    // 상세 패널이 열려 있으면 그 위로 띄운다. 패널 내용을 가리지 않게.
    const panel = document.querySelector('.detail');
    const gap = panel ? window.innerHeight - panel.getBoundingClientRect().top + 12 : 26;
    box.style.bottom = Math.min(gap, window.innerHeight - 140) + 'px';
    box.style.opacity = 1;
  };
  window.__cur = (x, y, show) => {
    const c = document.getElementById('demo-cur');
    if (x !== null) { c.style.left = x + 'px'; c.style.top = y + 'px'; }
    c.style.opacity = show === false ? 0 : 1;
  };
  window.__tap = () => {
    const c = document.getElementById('demo-cur');
    c.classList.add('tap');
    setTimeout(() => c.classList.remove('tap'), 220);
  };
  return 'ok';
}
"""


def log(*a):
    print(*a, flush=True)


def record(video_dir: Path, site: str) -> tuple[Path, float]:
    """화면을 돌면서 webm 을 남긴다. (영상 경로, 잘라낼 앞부분 초) 를 돌려준다."""
    pair = pick_pair(site)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--force-color-profile=srgb"])
        ctx_t0 = time.monotonic()
        ctx = browser.new_context(
            viewport={"width": W, "height": H},
            device_scale_factor=1,
            locale="en-US",
            record_video_dir=str(video_dir),
            record_video_size={"width": W, "height": H},
        )
        # 첫 방문 기본값 대신 데모용 배치를 미리 넣는다. 사람이 경계를 끌어
        # 맞춰 둔 상태와 같다. 근거 기사가 많은 관계를 열면 상세 패널이
        # 제 내용에 맞춰 자라면서 그래프를 거의 다 밀어내기 때문이다.
        ctx.add_init_script(
            """try {
              localStorage.setItem('board-lang', 'en');
              localStorage.setItem('board-nodeview', 'face');
              localStorage.setItem('board-layout', JSON.stringify(
                { rail: 300, feed: 292, detail: 400 }));
            } catch (e) {}"""
        )
        page = ctx.new_page()
        page.goto(site, wait_until="domcontentloaded", timeout=120_000)

        # 데이터가 다 붙을 때까지 기다린다. 서버가 자고 있으면 1분쯤 걸린다.
        page.wait_for_selector(".rank", timeout=180_000)
        page.wait_for_selector(".event", timeout=60_000)
        page.wait_for_timeout(9_000)  # 물리 시뮬레이션이 멎고 사진이 다 뜰 때까지

        assert page.evaluate(FIBER_HACK) == "ok", "vis-network 인스턴스를 못 찾았다"
        page.evaluate(OVERLAY)

        def cap(en, ko):
            page.evaluate("([en, ko]) => window.__cap(en, ko)", [en, ko])

        def cursor(x, y, show=True):
            page.evaluate("([x, y, s]) => window.__cur(x, y, s)", [x, y, show])

        def click_at(x, y, settle=700):
            cursor(x, y)
            page.wait_for_timeout(settle)
            page.evaluate("() => window.__tap()")
            page.mouse.click(x, y)

        def center_of(selector):
            box = page.locator(selector).first.bounding_box()
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

        demo_t0 = time.monotonic()
        offset = demo_t0 - ctx_t0
        log(f"[demo] 녹화 시작 지점 {offset:.2f}s")

        def hold_until(mark):
            left = mark - (time.monotonic() - demo_t0)
            if left > 0:
                page.wait_for_timeout(int(left * 1000))
            else:
                log(f"[demo] {mark}s 지점에서 {-left:.2f}s 늦음")

        # 1 ----------------------------------------------------- 전체 관계망
        cap(
            "296 members of Korea's 22nd National Assembly, read out of the daily press",
            "제22대 국회의원 296명, 매일의 뉴스에서 읽어낸 관계망",
        )
        page.evaluate(
            """() => {
              const n = window.__net;
              n.moveTo({ scale: n.getScale() * 1.12,
                         animation: { duration: 3000, easingFunction: 'easeInOutQuad' } });
            }"""
        )
        hold_until(4.0)

        # 2 ----------------------------------------------- 선을 읽는 법 (확대)
        cap(
            "Red is conflict, green is ally — dashed means only one press camp reported it",
            "빨강은 대립, 초록은 우호 — 점선은 한 진영만 보도한 관계",
        )
        page.evaluate(
            """() => {
              const n = window.__net;
              const deg = new Map();
              for (const e of n.body.data.edges.get()) {
                if (!e.label) continue;           // 우호·대립 선만 라벨이 있다
                deg.set(e.from, (deg.get(e.from) || 0) + 1);
                deg.set(e.to, (deg.get(e.to) || 0) + 1);
              }
              let hub = null, best = -1;
              for (const [id, d] of deg) if (d > best) { best = d; hub = id; }
              const pos = n.getPositions([hub])[hub];
              n.moveTo({ position: pos, scale: 1.08,
                         animation: { duration: 1800, easingFunction: 'easeInOutQuad' } });
            }"""
        )
        hold_until(8.2)

        # 3 ------------------------------------------------------ 화제성 순위
        cap(
            "Attention ranking — news mentions plus YouTube views over a 7-day window",
            "화제성 순위 — 최근 7일간의 뉴스 언급과 유튜브 조회수",
        )
        click_at(*center_of(".rank"), settle=900)
        page.wait_for_timeout(1200)
        cursor(None, None, False)
        hold_until(13.4)

        # 4 ------------------------------------------- 관계선을 눌러 근거 열기
        cap(
            "Click a relationship and the articles behind it open underneath",
            "관계선을 누르면 그 근거가 된 기사가 아래에 열립니다",
        )
        target = pair and page.evaluate(
            """(pair) => {
              const n = window.__net;
              const na = { id: pair.aId }, nb = { id: pair.bId };
              if (!n.body.nodes[na.id] || !n.body.nodes[nb.id]) return null;
              // 라벨이 있는 선만 호불호다. 같은 두 사람 사이에 언급선이 함께
              // 있으면 그것을 집어서는 근거가 열리지 않는다.
              const edge = n.body.data.edges.get().find(e => e.label &&
                ((e.from === na.id && e.to === nb.id) || (e.from === nb.id && e.to === na.id)));
              if (!edge) return null;
              const p = n.getPositions([na.id, nb.id]);
              const mid = { x: (p[na.id].x + p[nb.id].x) / 2, y: (p[na.id].y + p[nb.id].y) / 2 };
              const dist = Math.hypot(p[na.id].x - p[nb.id].x, p[na.id].y - p[nb.id].y);
              n.moveTo({ position: mid, scale: Math.min(1.45, 430 / Math.max(dist, 160)),
                         animation: { duration: 1500, easingFunction: 'easeInOutQuad' } });
              return { edgeId: edge.id, aId: na.id, bId: nb.id };
            }""",
            pair,
        )
        log("[demo] 대상 관계선:", target)
        page.wait_for_timeout(1700)

        point = target and page.evaluate(
            """(t) => {
              const n = window.__net;
              const p = n.getPositions([t.aId, t.bId]);
              const rect = document.querySelector('.canvas').getBoundingClientRect();
              // 선 위 여러 지점을 재 보고, 목표 선이 잡히는 자리를 고른다.
              for (const f of [0.5, 0.47, 0.53, 0.44, 0.56, 0.41, 0.59, 0.38, 0.62]) {
                const c = { x: p[t.aId].x + (p[t.bId].x - p[t.aId].x) * f,
                            y: p[t.aId].y + (p[t.bId].y - p[t.aId].y) * f };
                const d = n.canvasToDOM(c);
                if (d.x < 8 || d.y < 8 || d.x > rect.width - 8 || d.y > rect.height - 8) continue;
                // 노드가 위에 덮여 있으면 클릭이 사람에게 먼저 잡힌다.
                if (n.getNodeAt(d) !== undefined) continue;
                if (n.getEdgeAt(d) === t.edgeId)
                  return { x: rect.x + d.x, y: rect.y + d.y, hit: true };
              }
              // 집을 자리가 없으면 커서만 선 한가운데로 보낸다.
              const mid = { x: (p[t.aId].x + p[t.bId].x) / 2, y: (p[t.aId].y + p[t.bId].y) / 2 };
              const d = n.canvasToDOM(mid);
              return { x: rect.x + d.x, y: rect.y + d.y, hit: false };
            }""",
            target,
        )
        log("[demo] 클릭 지점:", point)

        if point and point["hit"]:
            click_at(point["x"], point["y"], settle=800)
            page.wait_for_timeout(700)
        elif point:
            # 선이 얼굴에 가려 실제 클릭은 노드를 집는다. 커서만 올려 두고
            # 같은 선을 코드로 연다. 화면에 나오는 결과는 클릭과 같다.
            cursor(point["x"], point["y"])
            page.wait_for_timeout(800)
            page.evaluate("() => window.__tap()")
            page.wait_for_timeout(250)

        opened = page.evaluate(
            """(t) => {
              if (document.querySelector('.detail.evidence')) return 'click';
              if (!t) return 'none';
              const n = window.__net;
              n.unselectAll();
              n.selectEdges([t.edgeId]);
              n.body.emitter.emit('selectEdge', { nodes: [], edges: [t.edgeId] });
              return 'fallback';
            }""",
            target,
        )
        if opened == "none":
            # 그 쌍이 그래프에서 사라졌으면 피드 첫 줄로 같은 패널을 연다.
            click_at(*center_of(".event.openable"), settle=600)
        log("[demo] 근거 패널:", opened)

        # 근거가 길면 패널이 첫 기사에 붙어 열려 머리말이 가려진다
        # (.detail 의 scroll-snap). 위로 한 번 굴려 사건 수와 신뢰도부터 보여 준다.
        # 근거 기사가 없는 관계도 있다(집계 이전에 만들어진 것). 그때는
        # 패널이 "근거 기록 없음" 을 띄우므로, 둘 중 먼저 오는 것을 기다린다.
        page.wait_for_selector(".detail.evidence .ev-articles, .detail.evidence .ev-note",
                               timeout=20_000)
        page.wait_for_timeout(500)
        page.evaluate(
            """() => {
              const el = document.querySelector('.detail.evidence');
              if (el) el.scrollBy({ top: -400, behavior: 'smooth' });
            }"""
        )
        page.wait_for_timeout(900)
        cursor(None, None, False)
        hold_until(18.6)

        # 5 --------------------------------------------------- 근거의 내용물
        head = page.evaluate(
            "() => document.querySelector('.detail.evidence')?.innerText?.slice(0, 120) || ''"
        )
        log("[demo] 패널 머리말:", head.replace("\n", " | ")[:120])
        cap(
            "Events, confidence, which press camps reported it — and the source sentence",
            "근거 사건 수와 신뢰도, 어느 진영이 보도했는지, 그리고 원문 문장",
        )
        hold_until(23.0)

        # 6 ------------------------------------------------------- 근거 기사
        cap(
            "Confidence rises only when outlets from opposing camps report it independently",
            "서로 다른 진영의 매체가 각자 보도했을 때만 신뢰도가 올라갑니다",
        )
        page.evaluate(
            """() => {
              const el = document.querySelector('.detail.evidence');
              if (!el) return;
              el.scrollTo({ top: Math.min(el.scrollHeight - el.clientHeight, 300),
                            behavior: 'smooth' });
            }"""
        )
        hold_until(26.4)

        # 7 --------------------------------------------------------- 한국어
        cap("Korean and English throughout", "한국어와 영어를 모두 지원합니다")
        click_at(*center_of(".langsel .langbtn"), settle=700)
        page.wait_for_timeout(600)
        cursor(None, None, False)
        hold_until(29.6)
        page.evaluate("() => window.__cap(null)")
        page.wait_for_timeout(600)

        log(f"[demo] 총 {time.monotonic() - demo_t0:.2f}s")
        video = Path(page.video.path())
        ctx.close()
        browser.close()

    return video, offset


def gifsicle_cmd() -> list[str] | None:
    """설치된 gifsicle, 없으면 npx 로 받아 쓰는 경로. 둘 다 없으면 None.

    윈도우에서 which("npx") 는 확장자 없는 셸 스크립트를 집는다. CreateProcess
    가 그걸 실행하지 못해 WinError 193 이 난다. .cmd 를 먼저 찾는다.
    """
    if shutil.which("gifsicle"):
        return ["gifsicle"]
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    return [npx, "--yes", "gifsicle"] if npx else None


def encode(video: Path, offset: float, out: Path, fps: int, seconds: float) -> None:
    """webm 을 잘라 GIF 로 만든다. 팔레트를 따로 뽑아야 색이 뭉개지지 않는다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        palette = Path(tmp) / "palette.png"
        raw = Path(tmp) / "raw.gif"
        scale = f"fps={fps},scale={GIF_W}:{GIF_H}:flags=lanczos"
        head = ["ffmpeg", "-v", "error", "-ss", f"{offset:.2f}", "-t", f"{seconds}", "-i", str(video)]
        subprocess.run(
            head + ["-vf", f"{scale},palettegen=max_colors=96:stats_mode=diff", "-y", str(palette)],
            check=True,
        )
        subprocess.run(
            head
            + [
                "-i",
                str(palette),
                "-lavfi",
                f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                "-y",
                str(raw),
            ],
            check=True,
        )
        gifsicle = gifsicle_cmd()
        if gifsicle:
            # 사진이 가득한 어두운 화면이라 손실 압축 없이는 12MB 를 넘는다.
            subprocess.run(
                gifsicle + ["-O3", "--lossy=150", "--colors", "64", str(raw), "-o", str(out)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        else:
            log("[demo] gifsicle 이 없어 압축을 건너뛴다. 파일이 커진다.")
            shutil.copy(raw, out)


def main() -> int:
    ap = argparse.ArgumentParser(description="README 데모 GIF 를 다시 찍는다")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "demo.gif")
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--fps", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--keep-video", action="store_true", help="원본 webm 을 남긴다")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        log("ffmpeg 이 필요하다.")
        return 1

    hold = tempfile.mkdtemp(prefix="syndeo-demo-")
    video, offset = record(Path(hold), args.site)
    encode(video, offset, args.out, args.fps, args.seconds)

    size = args.out.stat().st_size
    log(f"[demo] {args.out} / {size / 1024 / 1024:.1f}MB")
    if args.keep_video:
        log(f"[demo] 원본 영상: {video}")
    else:
        shutil.rmtree(hold, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
