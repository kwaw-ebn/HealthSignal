const CACHE='healthsignal-shell-v8';
const SHELL=['/','/static/styles.css?v=20260913-7','/static/auth.css?v=20260913-7','/static/surveillance.css?v=20260913-4','/static/app.js?v=20260921-1','/static/logo.jpg','/static/manifest.json'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{if(event.request.method!=='GET'||event.request.url.includes('/api/'))return;event.respondWith(fetch(event.request).then(response=>{let copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy));return response}).catch(()=>caches.match(event.request).then(hit=>hit||caches.match('/'))))});
