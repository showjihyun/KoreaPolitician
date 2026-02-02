# Testing Guide - Korea Politician Network

## Quick Start

All services are currently running! You can test the application immediately.

## 🌐 Access Points

### Frontend Application
- **URL**: http://localhost:3100
- **Description**: React-based 3D graph visualization
- **Features**:
  - Interactive 3D graph with politician photos
  - Search bar for finding politicians
  - Party-based color coding
  - Graph/List view toggle
  - Statistics panel

### Backend API
- **URL**: http://localhost:5000
- **Description**: FastAPI REST API
- **Swagger Docs**: http://localhost:5000/docs (if enabled)

### TuringDB Mock Server
- **URL**: http://localhost:6666
- **Description**: Health check server
- **Endpoint**: http://localhost:6666/health

## 🧪 API Testing

### 1. Get Statistics
```bash
curl http://localhost:5000/api/stats
```

Expected response:
```json
{
  "total_nodes": 308,
  "total_edges": 20589,
  "nodes_by_label": {
    "Party": 8,
    "Member": 300
  },
  "edges_by_type": {
    "BELONGS_TO": 300,
    "REPRESENTS": 10,
    "SAME_PARTY": 20279
  }
}
```

### 2. Search for a Politician
```bash
curl http://localhost:5000/api/search/이재명
```

Expected response:
```json
{
  "members": [
    {
      "name": "이재명",
      "id": "211",
      "party": "더불어민주당",
      "region": "",
      "election_count": "",
      "image_url": "/api/images/이재명.jpg",
      "thumbnail_url": "/api/images/이재명.jpg?thumbnail=true"
    }
  ]
}
```

### 3. Get Politician's Relationship Graph
```bash
curl "http://localhost:5000/api/graph/이재명?depth=2"
```

Returns nodes and relationships connected to the politician.

### 4. Get All Politicians Graph
```bash
curl "http://localhost:5000/api/graph/all?limit=50"
```

Returns a limited set of politicians and their relationships.

### 5. Get Politician Image
```bash
curl http://localhost:5000/api/images/이재명.jpg --output test.jpg
```

Downloads the politician's photo.

### 6. List All Available Images
```bash
curl http://localhost:5000/api/images
```

Returns list of all available politician images.

## 🎨 Frontend Testing

### 1. Open the Application
1. Open your browser
2. Navigate to http://localhost:3100
3. You should see the Korea Politician Network interface

### 2. Test Search Functionality
1. Click on the search bar
2. Type a politician's name (e.g., "이재명", "윤석열", "김기현")
3. Select from autocomplete suggestions
4. Graph should update to show the selected politician's network

### 3. Test 3D Graph Visualization
1. The graph should display in 3D with WebGL
2. **Check if politician photos appear** on the nodes
3. Use mouse to:
   - **Left-click + drag**: Rotate the graph
   - **Right-click + drag**: Pan the graph
   - **Scroll**: Zoom in/out
4. Hover over nodes to see politician details
5. Observe party-based color coding:
   - Blue: 더불어민주당
   - Red: 국민의힘
   - Orange: 조국혁신당
   - Gray: 무소속/기타

### 4. Test View Modes
1. Click "그래프 뷰" button - should show 3D graph
2. Click "리스트 뷰" button - should show grid of politicians
3. Toggle between views

### 5. Check Statistics Panel
1. Look at the right side panel
2. Should display:
   - Total politicians count
   - Total relationships count
   - Party distribution
   - Relationship type distribution

## 🐛 Troubleshooting

### Images Not Displaying in Graph
If politician photos don't appear in the 3D graph:

1. **Check browser console** (F12) for errors
2. **Verify image URLs** are being loaded:
   ```javascript
   // In browser console
   fetch('http://localhost:5000/api/images/이재명.jpg')
     .then(r => console.log('Image status:', r.status))
   ```
3. **Check CORS**: Images should be served with proper CORS headers
4. **Check image paths**: Verify `/img` volume is mounted correctly

### Backend Not Responding
```bash
# Check backend logs
docker logs korea-politician-backend

# Restart backend
docker-compose restart backend
```

### Frontend Not Loading
```bash
# Check frontend logs
docker logs korea-politician-frontend

# Restart frontend
docker-compose restart frontend
```

### TuringDB Unhealthy
```bash
# Check TuringDB logs
docker logs korea-politician-turingdb

# Restart TuringDB
docker-compose restart turingdb
```

## 📊 Expected Behavior

### Graph Visualization
- **Nodes**: Should display as spheres or sprites with politician photos
- **Edges**: Should display as lines connecting related politicians
- **Colors**: Different colors for different parties
- **Interactions**: Smooth rotation, panning, and zooming
- **Performance**: Should handle 300 nodes smoothly

### Search
- **Autocomplete**: Should suggest politicians as you type
- **Selection**: Clicking a suggestion should update the graph
- **Filtering**: Graph should show only selected politician and connections

### Statistics
- **Real-time**: Should update based on current graph view
- **Accurate**: Numbers should match the data loaded

## 🔍 Verification Checklist

- [ ] Frontend loads at http://localhost:3100
- [ ] Backend API responds at http://localhost:5000
- [ ] Statistics endpoint returns correct data
- [ ] Search functionality works
- [ ] 3D graph renders correctly
- [ ] **Politician photos display in graph nodes** ⚠️ NEEDS VERIFICATION
- [ ] Graph interactions work (rotate, pan, zoom)
- [ ] Party colors are correct
- [ ] View toggle works (Graph/List)
- [ ] Statistics panel shows correct numbers

## 🚀 Next Steps After Testing

If everything works:
1. ✅ Mark image display as verified
2. Consider running web crawlers for enhanced data
3. Implement additional relationship types
4. Add filter panel for advanced queries
5. Plan global expansion features

If issues found:
1. Document the issue
2. Check relevant logs
3. Verify configuration
4. Test API endpoints individually
5. Check browser console for frontend errors

---

**Testing Date**: January 28, 2026
**Tester**: [Your Name]
**Status**: Ready for testing
