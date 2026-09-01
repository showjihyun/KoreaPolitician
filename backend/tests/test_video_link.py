"""유튜브 링크 파서.

parse_view_count 와 같은 성격의 순수 함수다. 틀려도 예외가 안 나고 조용히
빈 값이 되기 때문에, 실패가 눈에 띄지 않는다. 로케일 문제로 조회수가 전부
0 이 됐던 일이 그랬다. 그래서 여기도 값으로 못 박아 둔다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawlers.sns_crawler_pipeline import video_id, video_post_id, watch_url

VID = "dQw4w9WgXcQ"


class TestVideoId:
    def test_상대경로에서_뽑는다(self):
        assert video_id(f"/watch?v={VID}&pp=ygUJ") == VID

    def test_절대주소에서_뽑는다(self):
        assert video_id(f"https://www.youtube.com/watch?v={VID}") == VID

    def test_단축주소를_받는다(self):
        assert video_id(f"https://youtu.be/{VID}") == VID

    def test_모바일_주소를_받는다(self):
        assert video_id(f"https://m.youtube.com/watch?v={VID}") == VID

    def test_흉내낸_도메인은_거른다(self):
        # 부분 일치로 검사하면 이런 주소가 통과해 화면의 링크로 나간다.
        assert video_id(f"https://www.youtube.com.attacker.example/watch?v={VID}") is None
        assert video_id(f"https://notyoutube.com/watch?v={VID}") is None

    def test_영상이_아니면_없다(self):
        assert video_id("/shorts/abc") is None
        assert video_id("/watch?v=") is None
        assert video_id(None) is None
        assert video_id("") is None


class TestWatchUrl:
    def test_정규_주소를_만든다(self):
        assert watch_url(VID) == f"https://www.youtube.com/watch?v={VID}"

    def test_없으면_없다(self):
        assert watch_url(None) is None


class TestVideoPostId:
    def test_영상_id_를_쓴다(self):
        assert video_post_id(VID, "제목") == f"yt_{VID}"

    def test_id_가_없으면_제목_해시로_떨어진다(self):
        pid = video_post_id(None, "국회의원 관련 영상")
        assert pid.startswith("yt_") and len(pid) == 13

    def test_제목이_바뀌면_해시_키는_달라진다(self):
        # 영상 id 를 쓰는 이유. 해시 키는 제목이 바뀌면 다른 영상이 된다.
        assert video_post_id(None, "제목 A") != video_post_id(None, "제목 B")
        assert video_post_id(VID, "제목 A") == video_post_id(VID, "제목 B")

    def test_옛_키와_새_키는_길이로_갈린다(self):
        # 중복 정리 SQL 이 '^yt_[0-9a-f]{10}$' 로 옛 키만 지운다.
        import re

        old = re.compile(r"^yt_[0-9a-f]{10}$")
        assert old.match(video_post_id(None, "제목"))
        assert not old.match(video_post_id(VID, "제목"))
