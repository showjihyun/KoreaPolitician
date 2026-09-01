import os
import threading
from collections import Counter
import time
import json
import logging
from datetime import datetime, timedelta
import requests
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright
import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv
from core.graph_storage import graph_storage, run_sync, close_sync
from core.db_config import close_sync_pool, db_config_from_env, get_sync_pool
from core.name_matcher import find_names
from core.hotness import update_summary, youtube_score
from crawlers.view_count import parse_view_count

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/sns_crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# POLITICIANS 명단 로드
from crawlers.news_crawler_pipeline import POLITICIANS

# 수집할 SNS 플랫폼. 쉼표로 구분해 SNS_PLATFORMS 환경변수로 바꿀 수 있다.
#
# X(트위터)와 인스타그램은 2026-08 기준 비로그인 수집이 막혀 있다.
# 첫 운영 크롤링(run 33261656351)에서 의원 296명 전원에 대해 다음이 반복됐다.
#
#   X crawl failed for OOO: Page.wait_for_selector: Timeout 20000ms exceeded
#     - waiting for locator("article") to be visible
#   Instagram access limited for OOO (possible login required)
#
# 18분을 쓰고 수집 0건이었으므로 기본값에서 제외한다. 크롤 함수 자체는
# 그대로 두었으므로, 로그인 세션을 붙일 수 있게 되면
# SNS_PLATFORMS=youtube,x,instagram 으로 되살리면 된다.
DEFAULT_SNS_PLATFORMS = "youtube"


# 유튜브가 내주는 주소로 인정할 호스트. 부분 일치로 검사하면
# youtube.com.attacker.example 같은 흉내 도메인이 통과한다.
_YT_HOSTS = frozenset((
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
))


def video_id(href):
    """검색 결과의 링크에서 영상 id 를 뽑는다. 못 알아보면 None.

    href 는 보통 '/watch?v=XXXX&pp=...' 로 오지만 절대 주소나 youtu.be
    단축 주소로 올 때도 있다. 추적용 뒷가지는 버린다.
    """
    if not href:
        return None
    parsed = urlparse(href if href.startswith("http") else "https://www.youtube.com" + href)
    if parsed.netloc and parsed.netloc.lower() not in _YT_HOSTS:
        return None
    if parsed.netloc.lower() == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
    else:
        vid = parse_qs(parsed.query).get("v", [None])[0]
    return vid or None


def watch_url(vid):
    """영상 id 를 정규 시청 주소로 만든다."""
    return f"https://www.youtube.com/watch?v={vid}" if vid else None


def video_post_id(vid, title):
    """영상 식별자. id 가 있으면 그것을, 없으면 제목 해시를 쓴다.

    제목 해시는 채널이 제목을 고치면 다른 영상으로 잡혀 중복이 쌓인다.
    영상 id 가 있으면 그쪽이 안정적이다.
    """
    if vid:
        return f"yt_{vid}"
    return f"yt_{hashlib.md5(title.encode()).hexdigest()[:10]}"

ENABLED_PLATFORMS = {
    p.strip().lower()
    for p in (os.getenv("SNS_PLATFORMS") or DEFAULT_SNS_PLATFORMS).split(",")
    if p.strip()
}
logger.info(f"활성 SNS 플랫폼: {sorted(ENABLED_PLATFORMS)}")

# 유튜브 수집 진단용 집계. 296명을 돌면서 매번 상세 로그를 남기면 로그가
# 뒤덮이므로, 원인 판별에 필요한 페이지 덤프는 앞쪽 몇 건만 남기고
# 나머지는 숫자로만 센다. 파이프라인 끝에서 한 번 요약한다.
YT_DIAG_DUMP_LIMIT = 3
yt_stats = Counter()
_yt_diag_lock = threading.Lock()


def _yt_note(key, n=1):
    with _yt_diag_lock:
        yt_stats[key] += n


def _yt_should_dump():
    with _yt_diag_lock:
        if yt_stats["dumped"] >= YT_DIAG_DUMP_LIMIT:
            return False
        yt_stats["dumped"] += 1
        return True


class SNSViralityCollector:
    def __init__(self):
        # 빈 문자열 환경변수(미등록 시크릿)를 미설정으로 처리한다.
        self.db_config = db_config_from_env()
        # Initialize GraphDB connection
        load_dotenv('backend/.env')
        run_sync(graph_storage.init_db(self.db_config))

        # 이름 -> ID 맵 구축 (최초 1회)
        self.name_to_id = {}
        members = graph_storage.find_nodes("Member")
        for m in members:
            self.name_to_id[m['properties'].get('name')] = m['id']

    def _update_summary(self, name):
        """의원별 화제성 요약 갱신.

        집계 로직은 core.hotness 로 옮겼다. 뉴스 기반 화제성도 같은 테이블을
        쓰므로, 두 경로가 같은 산식을 공유해야 플랫폼 간 비교가 성립한다.
        """
        update_summary(name)

    def _detect_and_save_interactions(self, source_name, text, platform, hot_score):
        """텍스트에서 다른 정치인 언급을 탐지하여 그래프 엣지로 저장"""
        source_id = self.name_to_id.get(source_name)
        if not source_id: return

        # 자신을 제외한 다른 정치인이 언급되었는지 확인.
        # 단순 부분일치는 '김건희' 에서 '김건' 을 뽑아내므로 공용 매처를 쓴다.
        # 후보 전체(POLITICIANS)를 넘겨야 긴 이름 우선 규칙이 동작한다.
        for target_name in find_names(text, POLITICIANS):
            if target_name == source_name:
                continue

            target_id = self.name_to_id.get(target_name)
            if target_id:
                # SNS_INTERACTION 관계 추가
                run_sync(graph_storage.add_edge(
                    source_id,
                    target_id,
                    "SNS_INTERACTION",
                    {
                        "platform": platform,
                        "impact": hot_score,
                        "content": text[:100],
                        "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                ))
                logger.info(f"  [Relation Found] {source_name} --[SNS]--> {target_name} ({platform})")

    def _save_to_db(self, data):
        # 예전에는 호출마다 psycopg.connect() 로 새 커넥션 + TLS 핸드셰이크를
        # 해서, 다중 스레드 실행 시 관리형 Postgres 의 커넥션 한도를 즉시
        # 소진했다. 공유 풀에서 빌리고 finally 에서 반드시 반납한다.
        pool = get_sync_pool()
        conn = None
        try:
            conn = pool.getconn()
            cur = conn.cursor()
            query = """
                INSERT INTO public.politician_sns_hotness
                (member_name, platform, author_type, post_id, content_preview, engagement_data, hot_score, sentiment_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (member_name, platform, post_id) DO UPDATE
                SET engagement_data = EXCLUDED.engagement_data,
                    hot_score = EXCLUDED.hot_score,
                    sentiment_score = EXCLUDED.sentiment_score,
                    collected_at = NOW()
            """
            cur.execute(query, (
                data['member_name'], data['platform'], data.get('author_type', 'Citizen'),
                data['post_id'], data['content_preview'], Jsonb(data['engagement_data']),
                data['hot_score'], data.get('sentiment_score', 0)
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"DB Save Error: {e}")
        finally:
            if conn is not None:
                pool.putconn(conn)

    def crawl_x_twitter(self, name):
        """X(Twitter) 리트윗/좋아요 수집 및 인플루언서 가중치 적용"""
        results = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(locale="ko-KR")
                page = context.new_page()
                query = f"{name} (리트윗 OR 의원 OR 정치 OR 국회)"
                search_url = f"https://x.com/search?q={requests.utils.quote(query)}&src=typed_query&f=top" # 'Top' 탭에서 인플루언서 위주 수집
                page.goto(search_url, timeout=60000)
                page.wait_for_selector('article', timeout=20000)

                tweets = page.query_selector_all('article')[:10]
                for i, tweet in enumerate(tweets):
                    try:
                        text_el = tweet.query_selector('[data-testid="tweetText"]')
                        if not text_el: continue
                        text = text_el.inner_text()

                        # 인플루언서 여부 확인 (파란 딱지/인증 계정)
                        verified = tweet.query_selector('[aria-label="인증된 계정"]') is not None
                        authority_weight = 3.0 if verified else 1.0

                        metrics = tweet.query_selector_all('[data-testid="app-text-transition-container"]')
                        rt_count = 0
                        like_count = 0
                        for m in metrics:
                            val = m.inner_text().strip()
                            if not val: continue
                            if 'K' in val: num = int(float(val.replace('K','')) * 1000)
                            elif 'M' in val: num = int(float(val.replace('M','')) * 1000000)
                            elif val.isdigit(): num = int(val)
                            else: continue
                            if rt_count == 0: rt_count = num
                            else: like_count = num

                        if rt_count > 5 or like_count > 20:
                            # 기본 점수에 인플루언서 가중치 적용
                            # NOTE: 이 점수는 정규화되지 않았다. X 를 다시 켜기
                            # 전에 core.hotness 의 0~100 스케일에 맞춰야 한다.
                            # 그렇지 않으면 유튜브가 그랬듯 화제성 순위를
                            # 이 플랫폼 혼자 좌우하게 된다.
                            base_score = (rt_count * 2.5) + (like_count * 1.0)
                            final_score = base_score * authority_weight

                            results.append({
                                "member_name": name,
                                "platform": "X",
                                "author_type": "Influencer" if verified else "Citizen",
                                "post_id": f"x_{hashlib.md5(text.encode()).hexdigest()[:10]}",
                                "content_preview": text[:150],
                                "engagement_data": {"rt": rt_count, "like": like_count, "verified": verified},
                                "hot_score": final_score,
                                "sentiment_score": 0
                            })
                    except: continue
                browser.close()
        except Exception as e:
            logger.warning(f"X crawl failed for {name}: {e}")
        return results

    def crawl_youtube(self, name):
        """YouTube 조회수 수집 및 채널 영향력 가중치 적용"""
        results = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # 로케일을 지정하지 않으면 러너 기본값(en-US)으로 응답이 와서
                # 조회수 표기가 'K/M' 형식이 된다. 한국어로 고정한다.
                context = browser.new_context(
                    locale="ko-KR",
                    extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"},
                )
                page = context.new_page()
                query = f"{name} 의원"
                search_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
                page.goto(search_url, timeout=60000)

                # 결과가 렌더링될 때까지 기다린다. 로컬에서는 대기 없이도
                # 잡히지만, 느린 CI 러너에서는 타이밍 차이가 날 수 있다.
                try:
                    page.wait_for_selector('ytd-video-renderer', timeout=15000)
                except Exception:
                    _yt_note("no_renderer")

                all_videos = page.query_selector_all('ytd-video-renderer')
                _yt_note("searched")
                _yt_note("videos_seen", len(all_videos))

                if not all_videos:
                    # 여기가 CI 에서 0건이 나오는 지점이다. 유튜브가 동의
                    # 페이지나 봇 체크를 띄우면 이 셀렉터가 비게 된다.
                    # 정체를 알 수 있게 앞쪽 몇 건만 페이지 단서를 남긴다.
                    _yt_note("empty_result")
                    if _yt_should_dump():
                        try:
                            title = page.title()
                            body = (page.inner_text("body") or "")[:300].replace("\n", " ")
                            logger.warning(
                                f"[YT 진단] {name}: 영상 0건. url={page.url[:110]}")
                            logger.warning(f"[YT 진단] page.title={title!r}")
                            logger.warning(f"[YT 진단] body[:300]={body!r}")
                        except Exception as diag_err:
                            logger.warning(f"[YT 진단] 페이지 정보 수집 실패: {diag_err!r}")

                videos = all_videos[:5]
                for i, video in enumerate(videos):
                    try:
                        title_el = video.query_selector('#video-title')
                        channel_el = video.query_selector('#channel-info #text')
                        if not title_el: continue
                        title = title_el.inner_text()
                        # 화면에서 영상을 눌렀을 때 원문으로 나갈 주소.
                        # DOM 판본에 따라 #video-title 이 <a> 이기도 하고,
                        # <a id="video-title-link"> 안의 문자열이기도 하다.
                        # 어느 쪽이든 잡히게 후보를 차례로 본다.
                        vid = video_id(title_el.get_attribute('href'))
                        if not vid:
                            for sel in ('a#video-title-link', 'a#video-title', 'a[href*="watch?v="]'):
                                el = video.query_selector(sel)
                                vid = el and video_id(el.get_attribute('href'))
                                if vid:
                                    break
                        if not vid:
                            # 조용히 제목 해시로 떨어지면 제목이 바뀔 때마다
                            # 중복이 쌓인다. 눈에 보이게 센다.
                            _yt_note("no_href")
                        video_url = watch_url(vid)
                        channel_name = channel_el.inner_text() if channel_el else "Unknown"

                        # 특정 대형 정치 채널 가중치 (예시)
                        is_news_channel = any(kw in channel_name for kw in ['TV', '뉴스', '커뮤니케이션', '방송', '정치'])
                        authority_weight = 5.0 if is_news_channel else 1.0

                        meta_el = video.query_selector('#metadata-line')
                        meta = meta_el.inner_text() if meta_el else ""
                        # 예전에는 '조회수' 문자열에만 의존해, en-US 로케일인 CI
                        # 러너에서 모든 조회수가 0 이 되어 전부 버려졌다.
                        view_count = parse_view_count(meta)

                        _yt_note("parsed")
                        if view_count <= 1000:
                            _yt_note("below_threshold")
                        if view_count > 1000:
                            # 예전에는 조회수에 0.05 를 곱해 그대로 썼다. 조회수가
                            # 수십만~수백만이라 점수가 100만 단위까지 나왔고,
                            # 뉴스(평균 54점)와 300배 차이가 나 화제성 순위가
                            # 사실상 유튜브만 반영했다. 로그로 압축해 정규화한다.
                            final_score = youtube_score(view_count, authority_weight)

                            results.append({
                                "member_name": name,
                                "platform": "YouTube",
                                "author_type": "Organization" if is_news_channel else "Influencer",
                                "post_id": video_post_id(vid, title),
                                "content_preview": f"[{channel_name}] {title}",
                                "engagement_data": {
                                    "views": view_count,
                                    "channel": channel_name,
                                    "url": video_url,
                                },
                                "hot_score": final_score
                            })
                    except Exception as item_err:
                        _yt_note("item_error")
                        logger.debug(f"[YT] {name} 영상 파싱 실패: {item_err!r}")
                        continue
                browser.close()
        except Exception as e:
            # 예전에는 맨 except 로 전부 삼켜서, CI 에서 0건이 나와도 원인을
            # 알 수 없었다.
            _yt_note("crawl_error")
            logger.warning(f"YouTube crawl failed for {name}: {type(e).__name__}: {e}")

        _yt_note("collected", len(results))
        if not results:
            _yt_note("member_zero")
        return results

    def crawl_instagram(self, name):
        """Instagram 해시태그 수집 및 인플루언서 가중치 적용"""
        results = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Instagram은 모바일 뷰에서 데이터 추출이 용이할 때가 많음
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1"
                )
                page = context.new_page()
                # 쿼리: 해시태그 검색
                tag = name.replace(" ", "")
                search_url = f"https://www.instagram.com/explore/tags/{tag}/"
                page.goto(search_url, timeout=60000)

                # 로그인 유도 팝업 등이 뜰 수 있으므로 예외 처리 강화
                try:
                    page.wait_for_selector('article img', timeout=15000)
                except:
                    logger.warning(f"Instagram access limited for {name} (possible login required)")
                    browser.close()
                    return []

                # 인기 게시물 위주로 확인 (보통 상단 9개)
                posts = page.query_selector_all('article a')[:5]
                for i, post in enumerate(posts):
                    try:
                        # 인스타그램은 상세 페이지를 가야 정확한 지표(좋아요)가 보임
                        # 여기서는 데모용으로 해시태그 노출 빈도와 상위 노출 여부로 점수 산정
                        # 실제 운영시 세션 쿠키를 통한 심층 크롤링 필요
                        authority_weight = 3.0 # 인기 게시물 탭에 노출된 것 자체가 영향력 지표

                        results.append({
                            "member_name": name,
                            "platform": "Instagram",
                            "author_type": "Influencer", # 인기 게시물 전제
                            "post_id": f"ig_{tag}_{i}",
                            "content_preview": f"#{tag} 인기 게시물",
                            "engagement_data": {"type": "top_post"},
                            "hot_score": 50.0 * authority_weight # 기본 점수 부여
                        })
                    except: continue
                browser.close()
        except Exception as e:
            logger.warning(f"Instagram crawl failed for {name}: {e}")
        return results

    def run_for_name(self, name):
        crawlers = {
            "x": self.crawl_x_twitter,
            "youtube": self.crawl_youtube,
            "instagram": self.crawl_instagram,
        }
        active = {k: fn for k, fn in crawlers.items() if k in ENABLED_PLATFORMS}
        if not active:
            logger.warning("활성화된 SNS 플랫폼이 없습니다.")
            return

        logger.info(f"SNS 화제성 분석 시작 ({'/'.join(sorted(active))}): {name}")
        all_data = []

        # 의원 한 명당 활성 플랫폼을 동시에 크롤링
        with ThreadPoolExecutor(max_workers=max(1, len(active))) as platform_executor:
            tasks = {platform_executor.submit(fn, name): key
                     for key, fn in active.items()}

            for future in as_completed(tasks):
                try:
                    res = future.result()
                    if res: all_data.extend(res)
                except Exception as e:
                    logger.error(f"Platform crawl error for {name} "
                                 f"({tasks[future]}): {e}")

        for d in all_data:
            self._save_to_db(d)
            # 관계 탐색 추가
            self._detect_and_save_interactions(
                d['member_name'],
                d['content_preview'],
                d['platform'],
                d['hot_score']
            )

        # 전체 수집 후 요약 정보 업데이트
        self._update_summary(name)

        if all_data:
            top_score = max([x['hot_score'] for x in all_data])
            logger.info(f"  -> {name}: {len(all_data)}건 수집 완료 (최고 화제성: {top_score:.1f})")
        return len(all_data)

    def run_pipeline(self):
        logger.info("=== SNS Virality Pipeline Start ===")
        # CPU 코어 수의 약 80%를 워커로 사용 (리소스 효율화)
        import multiprocessing
        max_workers = min(len(POLITICIANS), multiprocessing.cpu_count() * 2)
        logger.info(f"Setting MAX_WORKERS to {max_workers}")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 모든 국회의원(약 300명) 대상으로 병렬 실행
            futures = [executor.submit(self.run_for_name, name) for name in POLITICIANS]
            total = len(futures)
            completed = 0
            for future in as_completed(futures):
                completed += 1
                try:
                    future.result()
                    if completed % 10 == 0 or completed == total:
                        logger.info(f"Progress: [{completed}/{total}] SNS analysis in progress...")
                except Exception as e:
                    logger.error(f"Task Error: {e}")
        if "youtube" in ENABLED_PLATFORMS:
            s = yt_stats
            logger.info(
                "[YT 요약] 검색 %d회 / 영상 발견 %d개 / 결과 0건인 의원 %d명 / "
                "렌더러 대기실패 %d / 파싱 %d / 조회수미달 %d / 항목오류 %d / "
                "크롤오류 %d / 최종수집 %d건",
                s["searched"], s["videos_seen"], s["member_zero"], s["no_renderer"],
                s["parsed"], s["below_threshold"], s["item_error"],
                s["crawl_error"], s["collected"])

        self._drop_legacy_youtube_dupes()
        self._prune_old_rows()
        logger.info("=== SNS Virality Pipeline End ===")

    def _drop_legacy_youtube_dupes(self):
        """제목 해시로 저장돼 있던 옛 유튜브 행을 지운다.

        post_id 를 제목 해시에서 영상 id 로 바꾸면서, 같은 영상이 옛 키와 새
        키로 두 줄 남는다. UNIQUE 는 (member_name, platform, post_id) 라 upsert
        가 막아 주지 못한다. 그대로 두면 그 영상 점수가 두 번 더해져 일주일
        동안 순위를, 90일 동안 누적 점수를 부풀린다.

        옛 키는 md5 앞 10자리라 'yt_' + 소문자 16진수 10자다. 영상 id 는 11자
        이므로 길이만으로 갈린다. 같은 의원·같은 제목의 새 행이 실제로 들어온
        경우에만 지운다. 새로 수집되지 않은 옛 기록까지 날리지 않는다.
        """
        try:
            pool = get_sync_pool()
            conn = pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM public.politician_sns_hotness old
                        WHERE old.platform = 'YouTube'
                          AND old.post_id ~ '^yt_[0-9a-f]{10}$'
                          AND EXISTS (
                              SELECT 1 FROM public.politician_sns_hotness fresh
                              WHERE fresh.member_name = old.member_name
                                AND fresh.platform = 'YouTube'
                                AND fresh.post_id !~ '^yt_[0-9a-f]{10}$'
                                AND fresh.content_preview = old.content_preview
                          )
                        """
                    )
                    deleted = cur.rowcount
                conn.commit()
                if deleted:
                    logger.info(f"옛 키로 남아 있던 유튜브 중복 {deleted}건 삭제")
            finally:
                pool.putconn(conn)
        except Exception as exc:                               # noqa: BLE001
            logger.warning(f"유튜브 중복 정리 실패: {exc!r}")

    def _prune_old_rows(self):
        """오래된 화제성 행을 지운다.

        크롤러가 매일 INSERT 만 하고 삭제하지 않아, 무료 플랜 500MB 를
        채우는 것은 시간 문제였다. 요약 테이블에는 누적 점수가 남으므로
        원본 포스트는 보존 기간만 유지한다.
        """
        days = int(os.getenv("SNS_RETENTION_DAYS") or 90)
        try:
            pool = get_sync_pool()
            conn = pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM public.politician_sns_hotness "
                        "WHERE collected_at < NOW() - (%s || ' days')::interval",
                        (str(days),),
                    )
                    deleted = cur.rowcount
                conn.commit()
                logger.info(f"보존 기간({days}일) 초과 SNS 행 {deleted}건 삭제")
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"SNS 보존 정책 적용 실패: {e}")

if __name__ == "__main__":
    try:
        collector = SNSViralityCollector()
        collector.run_pipeline()
    finally:
        # 비동기 풀 / 전용 루프 / 동기 크롤러 풀 정리
        close_sync()
        close_sync_pool()
