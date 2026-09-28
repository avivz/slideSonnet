import { createRouter, createWebHistory } from 'vue-router'

import LibraryView from './features/library/LibraryView.vue'
import NotFoundView from './components/NotFoundView.vue'

// The deck editor (/d/:token) is still the NiceGUI page during the migration,
// so links to it are ordinary page loads, not router navigations.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'library', component: LibraryView },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
  ],
})
