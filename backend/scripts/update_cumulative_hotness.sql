-- SNS 누적 핫니스 데이터 갱신 스크립트
-- 기존 테이블에 cumulative_hot_score 컬럼이 없는 경우 추가
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='politician_hotness_summary' AND column_name='cumulative_hot_score') THEN
        ALTER TABLE public.politician_hotness_summary ADD COLUMN cumulative_hot_score FLOAT DEFAULT 0;
    END IF;
END $$;

-- 전체 이력을 기반으로 누적 점수 계산 및 갱신
WITH cumulative_scores AS (
    SELECT 
        member_name,
        SUM(hot_score) as total_score
    FROM public.politician_sns_hotness
    GROUP BY member_name
)
UPDATE public.politician_hotness_summary s
SET cumulative_hot_score = c.total_score
FROM cumulative_scores c
WHERE s.member_name = c.member_name;

-- 요약 테이블에 없는 의원이 있을 경우 삽입 (선택 사항)
INSERT INTO public.politician_hotness_summary (member_name, current_hot_score, cumulative_hot_score, top_platform)
SELECT 
    member_name, 
    0, 
    SUM(hot_score), 
    'N/A'
FROM public.politician_sns_hotness
WHERE member_name NOT IN (SELECT member_name FROM public.politician_hotness_summary)
GROUP BY member_name;
