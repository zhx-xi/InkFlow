import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// #1325：@xyflow/react 的样式表（.react-flow__node/.react-flow__edges 定位与 .react-flow__edge-path
// 描边全部来自该文件）——缺它图谱「看得到块、看不到线」。JS import 优于 index.css 内的 @import。
import '@xyflow/react/dist/style.css';
import './index.css';
import { App } from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
