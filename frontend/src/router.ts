import { createRouter, createWebHistory } from 'vue-router'

import NotFoundView from './components/NotFoundView.vue'
import LibraryView from './features/library/LibraryView.vue'

// The deck editor is loaded on demand: the library opens without it.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'library', component: LibraryView },
    { path: '/d/:token', name: 'deck', component: () => import('./features/editor/EditorView.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
  ],
})
