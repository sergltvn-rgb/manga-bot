(function initReaderUiModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createReaderUiManager(config) {
        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const getCurrentChapterIdx = (config && config.getCurrentChapterIdx) ? config.getCurrentChapterIdx : (() => 0);
        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);
        const getReadChapters = (config && config.getReadChapters) ? config.getReadChapters : (() => ({}));

        const navigateChapter = (config && config.navigateChapter) ? config.navigateChapter : (() => {});
        const backFromReader = (config && config.backFromReader) ? config.backFromReader : (() => {});
        const haptic = (config && config.haptic) ? config.haptic : (() => {});
        const toggleFab = (config && config.toggleFab) ? config.toggleFab : (() => {});

        const doc = global.document;

        let lightboxImages = [];
        let lightboxIdx = 0;
        let lightboxZoomed = false;

        let lbTouchStartY = 0;
        let lbTouchDeltaY = 0;
        let lbSwiping = false;
        let lightboxInteractionsBound = false;

        let tocItems = [];

        let autoscrollActive = false;
        let autoscrollEnabled = false;
        let autoscrollSpeed = 3;
        let autoscrollRAF = null;
        let autoscrollInteractionsBound = false;

        let gesturesBound = false;

        function getReaderContent() {
            return doc ? doc.getElementById('reader-content') : null;
        }

        function initLightbox() {
            const container = doc ? doc.getElementById('reader-text') : null;
            if (!container) return;

            const imgs = container.querySelectorAll('img');
            lightboxImages = Array.from(imgs);

            imgs.forEach((img, i) => {
                img.style.cursor = 'zoom-in';
                img.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    openLightbox(i);
                };
            });
        }

        function openLightbox(idx) {
            if (!doc || lightboxImages.length === 0) return;
            lightboxIdx = idx;
            lightboxZoomed = false;

            const overlay = doc.getElementById('lightbox-overlay');
            const img = doc.getElementById('lightbox-img');
            if (!overlay || !img || !lightboxImages[idx]) return;

            img.src = lightboxImages[idx].src;
            img.classList.remove('zoomed');
            img.style.transform = '';
            overlay.classList.remove('hidden');
            updateLightboxNav();
            doc.body.style.overflow = 'hidden';
        }

        function closeLightbox() {
            if (!doc) return;
            const overlay = doc.getElementById('lightbox-overlay');
            if (overlay) overlay.classList.add('hidden');
            doc.body.style.overflow = '';
            lightboxZoomed = false;
        }

        function lightboxNavigate(delta) {
            if (!doc) return;
            const newIdx = lightboxIdx + delta;
            if (newIdx < 0 || newIdx >= lightboxImages.length) return;

            lightboxIdx = newIdx;
            const img = doc.getElementById('lightbox-img');
            if (!img || !lightboxImages[lightboxIdx]) return;

            img.src = lightboxImages[lightboxIdx].src;
            img.classList.remove('zoomed');
            img.style.transform = '';
            lightboxZoomed = false;
            updateLightboxNav();
        }

        function updateLightboxNav() {
            if (!doc) return;

            const prev = doc.getElementById('lightbox-prev');
            const next = doc.getElementById('lightbox-next');
            const counter = doc.getElementById('lightbox-counter');
            if (!prev || !next || !counter) return;

            prev.disabled = lightboxIdx === 0;
            next.disabled = lightboxIdx >= lightboxImages.length - 1;
            counter.textContent = `${lightboxIdx + 1} / ${lightboxImages.length}`;

            if (lightboxImages.length <= 1) {
                prev.style.display = 'none';
                next.style.display = 'none';
                counter.style.display = 'none';
            } else {
                prev.style.display = '';
                next.style.display = '';
                counter.style.display = '';
            }
        }

        function initLightboxInteractions() {
            if (!doc || lightboxInteractionsBound) return;
            lightboxInteractionsBound = true;

            const lbImg = doc.getElementById('lightbox-img');
            const lbWrapper = doc.getElementById('lightbox-image-wrapper');

            if (lbImg) {
                lbImg.addEventListener('click', () => {
                    if (lbSwiping) return;
                    lightboxZoomed = !lightboxZoomed;
                    lbImg.classList.toggle('zoomed', lightboxZoomed);
                    lbImg.style.transform = lightboxZoomed ? 'scale(2)' : '';
                });
            }

            if (lbWrapper) {
                lbWrapper.addEventListener('touchstart', (e) => {
                    if (lightboxZoomed) return;
                    lbTouchStartY = e.touches[0].clientY;
                    lbSwiping = false;
                    lbWrapper.style.transition = 'none';
                }, { passive: true });

                lbWrapper.addEventListener('touchmove', (e) => {
                    if (lightboxZoomed) return;
                    lbTouchDeltaY = e.touches[0].clientY - lbTouchStartY;
                    if (Math.abs(lbTouchDeltaY) > 10) {
                        lbSwiping = true;
                        const opacity = Math.max(0, 1 - Math.abs(lbTouchDeltaY) / 300);
                        lbWrapper.style.transform = `translateY(${lbTouchDeltaY}px)`;

                        const overlay = doc.getElementById('lightbox-overlay');
                        if (overlay) {
                            overlay.style.background = `rgba(0,0,0,${0.95 * opacity})`;
                        }
                    }
                }, { passive: true });

                lbWrapper.addEventListener('touchend', () => {
                    if (lightboxZoomed) return;
                    lbWrapper.style.transition = '';

                    if (Math.abs(lbTouchDeltaY) > 120) {
                        haptic('light');
                        closeLightbox();
                    }

                    lbWrapper.style.transform = '';
                    const overlay = doc.getElementById('lightbox-overlay');
                    if (overlay) overlay.style.background = '';

                    setTimeout(() => {
                        lbSwiping = false;
                    }, 100);
                    lbTouchDeltaY = 0;
                }, { passive: true });
            }
        }

        function buildToC() {
            if (!doc) return;

            const tocList = doc.getElementById('toc-list');
            if (!tocList) return;

            const chapters = getCurrentChapters();
            const currentChapterIdx = getCurrentChapterIdx();
            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            const readChapters = getReadChapters() || {};

            if (!chapters || chapters.length === 0) {
                tocList.innerHTML = '<div class="no-chapters">\u0421\u043f\u0438\u0441\u043e\u043a \u0433\u043b\u0430\u0432 \u043f\u0443\u0441\u0442</div>';
                return;
            }

            if (!series || !volume) {
                tocList.innerHTML = '<div class="no-chapters">\u0414\u0430\u043d\u043d\u044b\u0435 \u0441\u0435\u0440\u0438\u0438 \u043d\u0435 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u044b</div>';
                return;
            }

            tocList.innerHTML = chapters.map((ch, idx) => {
                const isActive = idx === currentChapterIdx;
                const chapterReadKey = ch.id || `${series.id}_v${volume.volume}_ch${ch.chapter}`;
                const isRead = !!readChapters[chapterReadKey];
                return `
                    <div class="toc-item ${isActive ? 'active' : ''} ${isRead ? 'read' : ''}" 
                         onclick="openChapter(${idx}); toggleToC();">
                        <span class="toc-num">${idx + 1}.</span>
                        <span class="toc-name">${ch.custom_name || '\u0413\u043b\u0430\u0432\u0430 ' + ch.chapter}</span>
                        ${isActive ? '<span class="toc-status-icon">\u{1F4CD}</span>' : (isRead ? '<span class="toc-status-icon">\u2713</span>' : '')}
                    </div>
                `;
            }).join('');

            const headingContainer = doc.getElementById('reader-text');
            tocItems = headingContainer ? Array.from(headingContainer.querySelectorAll('h1, h2, h3')) : [];

            setTimeout(() => {
                const activeItem = tocList.querySelector('.toc-item.active');
                if (activeItem) {
                    activeItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }, 100);
        }

        function highlightToCItem(idx) {
            if (!doc) return;
            doc.querySelectorAll('.toc-item').forEach((item, i) => {
                item.classList.toggle('active', i === idx);
            });
        }

        function scrollToHeading(idx) {
            if (!tocItems[idx]) return;
            const content = getReaderContent();
            if (content) {
                content.scrollTo({ top: tocItems[idx].offsetTop - 60, behavior: 'smooth' });
            }
            toggleToC();
        }

        function toggleToC() {
            if (!doc) return;
            const overlay = doc.getElementById('toc-overlay');
            const panel = doc.getElementById('toc-panel');
            if (overlay) overlay.classList.toggle('active');
            if (panel) panel.classList.toggle('active');
        }

        function toggleAutoscrollSetting(enabled) {
            autoscrollEnabled = !!enabled;
            if (!doc) return;

            const fab = doc.getElementById('autoscroll-fab');
            const speedGroup = doc.getElementById('autoscroll-speed-group');
            if (fab) fab.classList.toggle('hidden', !autoscrollEnabled);
            if (speedGroup) speedGroup.style.display = autoscrollEnabled ? 'block' : 'none';
            if (!autoscrollEnabled) stopAutoscroll();
        }

        function isAutoscrollEnabled() {
            return autoscrollEnabled;
        }

        function setAutoscrollSpeed(val) {
            const parsed = parseInt(val, 10);
            autoscrollSpeed = Number.isFinite(parsed) ? parsed : autoscrollSpeed;
        }

        function toggleAutoscroll() {
            if (autoscrollActive) stopAutoscroll();
            else startAutoscroll();
        }

        function startAutoscroll() {
            if (autoscrollActive || !doc) return;
            autoscrollActive = true;

            const fab = doc.getElementById('autoscroll-fab');
            if (fab) {
                fab.classList.add('scrolling');
                fab.textContent = '\u23F8';
            }

            const el = getReaderContent();
            if (!el) return;

            let lastTime = null;
            function step(ts) {
                if (!autoscrollActive) return;
                if (lastTime !== null) {
                    const dt = ts - lastTime;
                    const px = (autoscrollSpeed * 0.3) * (dt / 16.67);
                    el.scrollTop += px;
                    if (el.scrollTop >= el.scrollHeight - el.clientHeight) {
                        stopAutoscroll();
                        return;
                    }
                }
                lastTime = ts;
                autoscrollRAF = global.requestAnimationFrame(step);
            }
            autoscrollRAF = global.requestAnimationFrame(step);
        }

        function stopAutoscroll() {
            autoscrollActive = false;
            if (autoscrollRAF) global.cancelAnimationFrame(autoscrollRAF);
            autoscrollRAF = null;

            if (!doc) return;
            const fab = doc.getElementById('autoscroll-fab');
            if (fab) {
                fab.classList.remove('scrolling');
                fab.textContent = '\u25B6';
            }
        }

        function initAutoscrollInteractions() {
            if (autoscrollInteractionsBound) return;
            autoscrollInteractionsBound = true;

            const rc = getReaderContent();
            if (rc) {
                rc.addEventListener('touchstart', () => {
                    if (autoscrollActive) stopAutoscroll();
                }, { passive: true });
            }
        }

        function initGestures() {
            if (!doc || gesturesBound) return;
            gesturesBound = true;

            const reader = doc.getElementById('screen-reader');
            const content = getReaderContent();
            const indicator = doc.getElementById('swipe-back-indicator');
            const pullNext = doc.getElementById('pull-next-indicator');
            if (!reader || !content || !indicator || !pullNext) return;

            let touchStartX = 0;
            let gestureTouchStartY = 0;
            let isSwipeActive = false;
            let isGlobalPullingNext = false;

            const SWIPE_EDGE_MAX_X = 35;
            const SWIPE_MIN_DELTA_X = 10;
            const SWIPE_MAX_DELTA_Y = 40;
            const SWIPE_TRIGGER_THRESHOLD = 85;

            reader.addEventListener('pointerdown', (e) => {
                touchStartX = e.clientX;
                gestureTouchStartY = e.clientY;
                isSwipeActive = touchStartX < SWIPE_EDGE_MAX_X;
            }, { passive: true });

            reader.addEventListener('pointermove', (e) => {
                if (!isSwipeActive) return;
                const deltaX = e.clientX - touchStartX;
                const deltaY = Math.abs(e.clientY - gestureTouchStartY);
                if (deltaX > SWIPE_MIN_DELTA_X && deltaY < SWIPE_MAX_DELTA_Y) {
                    indicator.style.opacity = Math.min(deltaX / 100, 0.8);
                    indicator.style.transform = `translateY(-50%) scaleY(${Math.min(0.5 + deltaX / 200, 1)}) translateX(${deltaX / 2}px)`;
                }
            }, { passive: true });

            reader.addEventListener('pointerup', (e) => {
                const deltaX = e.clientX - touchStartX;
                indicator.style.opacity = 0;
                indicator.style.transform = 'translateY(-50%) translateX(-100%)';
                if (isSwipeActive && deltaX > SWIPE_TRIGGER_THRESHOLD) {
                    haptic('medium');
                    backFromReader();
                }
                isSwipeActive = false;
            }, { passive: true });

            let pullTouchStartY = 0;
            let pullDistance = 0;
            const pullNextText = pullNext.querySelector('#pull-next-text') || doc.getElementById('pull-next-text');
            const pullNextArrow = pullNext.querySelector('.pull-next-arrow');

            const onStart = (e) => {
                const scrollTop = content.scrollTop;
                const scrollHeight = content.scrollHeight;
                const clientHeight = content.clientHeight;

                if (!e.touches && (scrollTop + clientHeight < scrollHeight - 50)) {
                    pullTouchStartY = 0;
                    return;
                }

                pullTouchStartY = e.touches ? e.touches[0].clientY : e.clientY;
                pullDistance = 0;
                isGlobalPullingNext = false;
            };

            const onMove = (e) => {
                const chapters = getCurrentChapters();
                const currentChapterIdx = getCurrentChapterIdx();
                if (currentChapterIdx >= chapters.length - 1 || pullTouchStartY === 0) return;

                const touchY = e.touches ? e.touches[0].clientY : e.clientY;
                const scrollTop = content.scrollTop;
                const scrollHeight = content.scrollHeight;
                const clientHeight = content.clientHeight;

                if (isGlobalPullingNext || (Math.ceil(scrollTop + clientHeight) >= scrollHeight - 1)) {
                    const diff = pullTouchStartY - touchY;
                    if (diff > 15) {
                        if (!isGlobalPullingNext) {
                            isGlobalPullingNext = true;
                            haptic('light');
                        }
                        if (e.cancelable && e.touches) e.preventDefault();

                        pullDistance = diff;
                        pullNext.style.display = 'flex';
                        pullNext.style.opacity = Math.min(diff / 100, 1);

                        if (diff > 80) {
                            if (pullNextText) pullNextText.textContent = '\u041e\u0442\u043f\u0443\u0441\u0442\u0438\u0442\u0435 \u0434\u043b\u044f \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0439 \u0433\u043b\u0430\u0432\u044b';
                            if (pullNextArrow) pullNextArrow.style.transform = 'rotate(180deg)';
                        } else {
                            if (pullNextText) pullNextText.textContent = '\u0422\u044f\u043d\u0438\u0442\u0435 \u0434\u043b\u044f \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0439 \u0433\u043b\u0430\u0432\u044b';
                            if (pullNextArrow) pullNextArrow.style.transform = 'rotate(0deg)';
                        }
                    } else if (isGlobalPullingNext && diff < 5) {
                        isGlobalPullingNext = false;
                        pullNext.style.display = 'none';
                        pullDistance = 0;
                    }
                }
            };

            const onEnd = () => {
                if (isGlobalPullingNext && pullDistance > 80) {
                    haptic('medium');
                    navigateChapter(1);
                }
                pullNext.style.display = 'none';
                pullDistance = 0;
                isGlobalPullingNext = false;
                if (pullNextArrow) pullNextArrow.style.transform = 'rotate(0deg)';
            };

            content.addEventListener('touchstart', onStart, { passive: true });
            content.addEventListener('touchmove', onMove, { passive: false });
            content.addEventListener('touchend', onEnd);

            content.addEventListener('mousedown', onStart);
            doc.addEventListener('mousemove', (e) => {
                if (pullTouchStartY && !e.touches) onMove(e);
            });
            doc.addEventListener('mouseup', () => {
                if (pullTouchStartY) {
                    onEnd();
                    pullTouchStartY = 0;
                }
            });
        }

        return {
            initLightbox,
            openLightbox,
            closeLightbox,
            lightboxNavigate,
            updateLightboxNav,
            initLightboxInteractions,
            buildToC,
            highlightToCItem,
            scrollToHeading,
            toggleToC,
            toggleAutoscrollSetting,
            isAutoscrollEnabled,
            setAutoscrollSpeed,
            toggleAutoscroll,
            startAutoscroll,
            stopAutoscroll,
            initAutoscrollInteractions,
            initGestures
        };
    }

    root.createReaderUiManager = createReaderUiManager;
})(window);
