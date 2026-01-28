# Graph View Auto-Align Fix

## Issue
그래프 뷰에서 데이터가 화면 오른쪽에 몰려서 표시되는 문제가 있었습니다.

## Solution

### 1. TypeScript Build Error 수정
**문제**: `d3Force`와 `d3ForceStrength` props가 ForceGraph3D 컴포넌트에 존재하지 않아 빌드 실패

**해결**: 해당 props 제거
```typescript
// 제거된 코드:
d3Force="charge"
d3ForceStrength={-120}
```

### 2. 자동 정렬 기능 추가

#### 자동 정렬 함수
```typescript
const handleAutoAlign = () => {
  if (graphRef.current) {
    graphRef.current.zoomToFit(400, 50)
    
    // 카메라를 정면으로 리셋
    const distance = 300
    graphRef.current.cameraPosition(
      { x: 0, y: 0, z: distance },
      { x: 0, y: 0, z: 0 },
      1000
    )
  }
}
```

#### 데이터 로드 시 자동 정렬
```typescript
useEffect(() => {
  // ... 데이터 처리 ...
  
  if (graphRef.current) {
    setTimeout(() => {
      graphRef.current.zoomToFit(400, 50)
      
      const distance = 300
      graphRef.current.cameraPosition(
        { x: 0, y: 0, z: distance },
        { x: 0, y: 0, z: 0 },
        1000
      )
    }, 500)
  }
}, [memberGraph, allGraph, selectedMember])
```

#### 물리 엔진 정지 시 자동 정렬
```typescript
<ForceGraph3D
  onEngineStop={() => {
    if (graphRef.current) {
      graphRef.current.zoomToFit(400, 50)
    }
  }}
/>
```

### 3. UI 개선

#### 자동 정렬 버튼 추가
```typescript
<button
  className="control-btn align-btn"
  onClick={handleAutoAlign}
  title="그래프를 화면 중앙에 맞춤"
>
  🎯 자동 정렬
</button>
```

#### 버튼 스타일링
```css
.control-btn.align-btn {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border-color: #10b981;
  color: white;
  font-weight: 600;
}

.control-btn.align-btn:hover {
  background: linear-gradient(135deg, #059669 0%, #047857 100%);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
}
```

## 작동 방식

1. **초기 로드**: 데이터가 로드되면 500ms 후 자동으로 그래프를 화면 중앙에 배치
2. **물리 엔진 정지**: 노드들의 움직임이 멈추면 자동으로 화면에 맞춤
3. **수동 정렬**: 사용자가 "🎯 자동 정렬" 버튼을 클릭하여 언제든지 그래프를 중앙에 재배치

## 결과

- ✅ TypeScript 빌드 에러 해결
- ✅ 그래프가 화면 중앙에 자동으로 배치됨
- ✅ 사용자가 수동으로 정렬할 수 있는 버튼 추가
- ✅ 물리 엔진이 안정화되면 자동으로 화면에 맞춤

## 테스트

1. 브라우저에서 http://localhost:3100 접속
2. 그래프 뷰 확인 - 데이터가 화면 중앙에 표시되는지 확인
3. "🎯 자동 정렬" 버튼 클릭 - 그래프가 중앙으로 이동하는지 확인
4. 노드를 드래그하여 이동 후 자동 정렬 버튼 클릭 - 다시 중앙으로 돌아오는지 확인

## 파일 변경사항

- `KoreaPolitician/frontend/src/components/GraphVisualization.tsx` - 자동 정렬 로직 추가, 잘못된 props 제거
- `KoreaPolitician/frontend/src/components/GraphVisualization.css` - 자동 정렬 버튼 스타일 추가
