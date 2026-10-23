import { createRoot } from 'react-dom/client';
import { App } from './App';
import { Overlay } from './Overlay';
import { ComponentLab } from './ComponentLab';
import { KnowledgeWindow } from './Knowledge';
import './style.css';
import 'virtual:qt-theme.css';

createRoot(document.getElementById('root')!).render(location.hash === '#knowledge' ? <KnowledgeWindow /> : location.hash === '#overlay' ? <Overlay /> : location.hash === '#components' ? <ComponentLab /> : <App />);
