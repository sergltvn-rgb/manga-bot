(function initSettingsUiModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createSettingsUiManager(config) {
        const doc = global.document;
        const getSettings = (config && config.getSettings) ? config.getSettings : (() => ({}));
        const persistSettings = (config && config.persistSettings) ? config.persistSettings : (() => {});
        const applyIframeDarkMode = (config && config.applyIframeDarkMode) ? config.applyIframeDarkMode : (() => {});
        const haptic = (config && config.haptic) ? config.haptic : (() => {});
        const tg = (config && config.tg) ? config.tg : null;

        function setFontSize(size) {
            const settings = getSettings();
            settings.fontSize = parseInt(size, 10);

            const label = doc.getElementById('label-fontSize');
            if (label) label.innerText = size + 'px';

            applySettings();
            persistSettings();

            doc.querySelectorAll('[data-size]').forEach((button) => {
                button.classList.toggle('active', parseInt(button.dataset.size, 10) === parseInt(size, 10));
            });
        }

        function setTheme(theme) {
            const settings = getSettings();
            settings.theme = theme;
            applySettings();
            persistSettings();
            updateSettingsUI();
        }

        function setTextWidth(width) {
            const settings = getSettings();
            settings.textWidth = parseInt(width, 10);

            const label = doc.getElementById('label-textWidth');
            if (label) label.innerText = width + '%';

            applySettings();
            persistSettings();
        }

        function setFont(font) {
            const settings = getSettings();
            settings.font = font;
            applySettings();
            persistSettings();
            updateSettingsUI();
        }

        function setLineHeight(lineHeight) {
            const settings = getSettings();
            settings.lineHeight = parseFloat(lineHeight);

            const label = doc.getElementById('label-lineHeight');
            if (label) label.innerText = lineHeight;

            applySettings();
            persistSettings();
        }

        function setLetterSpacing(letterSpacing) {
            const settings = getSettings();
            settings.letterSpacing = parseFloat(letterSpacing);

            const label = doc.getElementById('label-letterSpacing');
            if (label) label.innerText = letterSpacing + 'px';

            applySettings();
            persistSettings();
        }

        function setParaIndent(indentPx) {
            const settings = getSettings();
            settings.paraIndent = parseInt(indentPx, 10);

            const label = doc.getElementById('label-paraIndent');
            if (label) label.innerText = indentPx + 'px';

            applySettings();
            persistSettings();
        }

        function setTextAlign(align) {
            const settings = getSettings();
            settings.textAlign = align;
            applySettings();
            persistSettings();
            updateSettingsUI();
        }

        function setIndent(enabled) {
            const settings = getSettings();
            settings.indent = enabled;

            const group = doc.getElementById('para-indent-group');
            if (group) group.style.display = enabled ? 'block' : 'none';

            applySettings();
            persistSettings();
        }

        function toggleSettings() {
            const overlay = doc.getElementById('settings-overlay');
            const panel = doc.getElementById('settings-panel');
            if (!overlay || !panel) return;

            const isHidden = panel.classList.contains('hidden');

            overlay.classList.toggle('hidden');
            panel.classList.toggle('hidden');

            if (!isHidden) {
                persistSettings();
            } else {
                showSettingsTab('font');
                updateSettingsUI();
            }
        }

        function showSettingsTab(tabName) {
            const contents = doc.querySelectorAll('.settings-tab-content');
            const buttons = doc.querySelectorAll('.settings-tab-btn');

            contents.forEach((content) => {
                content.classList.add('hidden');
                content.classList.remove('animate-slide-in');
            });

            buttons.forEach((button) => button.classList.remove('active'));

            const activeContent = doc.getElementById(`settings-tab-${tabName}`);
            if (activeContent) {
                activeContent.classList.remove('hidden');
                activeContent.classList.add('animate-slide-in');
            }

            const activeButton = doc.getElementById(`tab-btn-${tabName}`);
            if (activeButton) activeButton.classList.add('active');
        }

        function updateSettingsUI() {
            const settings = getSettings();

            if (doc.getElementById('label-fontSize')) doc.getElementById('label-fontSize').innerText = settings.fontSize + 'px';
            if (doc.getElementById('label-textWidth')) doc.getElementById('label-textWidth').innerText = settings.textWidth + '%';
            if (doc.getElementById('label-lineHeight')) doc.getElementById('label-lineHeight').innerText = settings.lineHeight;
            if (doc.getElementById('label-dimmerValue')) doc.getElementById('label-dimmerValue').innerText = settings.dimmerValue + '%';

            if (doc.getElementById('input-fontSize')) doc.getElementById('input-fontSize').value = settings.fontSize;
            if (doc.getElementById('input-textWidth')) doc.getElementById('input-textWidth').value = settings.textWidth;
            if (doc.getElementById('input-lineHeight')) doc.getElementById('input-lineHeight').value = settings.lineHeight;
            if (doc.getElementById('input-dimmerValue')) doc.getElementById('input-dimmerValue').value = settings.dimmerValue;

            doc.querySelectorAll('[data-font]').forEach((button) => {
                button.classList.toggle('active', button.dataset.font === settings.font);
            });
            doc.querySelectorAll('[data-align]').forEach((button) => {
                button.classList.toggle('active', button.dataset.align === settings.textAlign);
            });
            doc.querySelectorAll('[data-theme]').forEach((button) => {
                button.classList.toggle('active', button.dataset.theme === settings.theme);
            });
        }

        function setDimmer(value) {
            const settings = getSettings();
            settings.dimmerValue = parseInt(value, 10);

            const label = doc.getElementById('label-dimmerValue');
            if (label) label.innerText = value + '%';

            applySettings();
            persistSettings();
        }

        function applySettings() {
            const settings = getSettings();

            doc.body.className = '';
            if (settings.theme !== 'light') {
                doc.body.classList.add(`theme-${settings.theme}`);
            }

            const dimmer = doc.getElementById('dimmer-overlay');
            if (dimmer) {
                dimmer.style.backgroundColor = `rgba(0, 0, 0, ${settings.dimmerValue / 100})`;
                dimmer.style.pointerEvents = 'none';
            }

            const readerText = doc.getElementById('reader-text');
            if (readerText) {
                readerText.style.fontSize = settings.fontSize + 'px';
                readerText.style.maxWidth = settings.textWidth + '%';
                readerText.style.lineHeight = settings.lineHeight;
                readerText.style.letterSpacing = settings.letterSpacing + 'px';

                readerText.classList.remove('font-sans', 'font-slab', 'font-mono', 'font-montserrat', 'font-display');
                if (settings.font === 'sans') readerText.classList.add('font-sans');
                if (settings.font === 'montserrat') readerText.classList.add('font-montserrat');
                if (settings.font === 'display') readerText.classList.add('font-display');

                readerText.classList.toggle('align-justify', settings.textAlign === 'justify');
                readerText.classList.toggle('indent-on', settings.indent);

                readerText.style.setProperty('--para-spacing', settings.paraSpacing + 'px');
                readerText.style.setProperty('--para-indent', settings.paraIndent + 'px');
            }

            const socialSection = doc.getElementById('social-section');
            if (socialSection) {
                socialSection.style.maxWidth = settings.textWidth + '%';
            }

            applyIframeDarkMode();
            haptic('light');

            try {
                const colors = {
                    light: '#ffffff',
                    sepia: '#f4ead5',
                    gray: '#333333',
                    dark: '#1a1a2e',
                    amoled: '#000000'
                };
                if (tg && typeof tg.setHeaderColor === 'function') {
                    tg.setHeaderColor(colors[settings.theme] || '#ffffff');
                }
            } catch (e) {
                // ignore
            }
        }

        function restoreSettings() {
            updateSettingsUI();
            applySettings();
        }

        return {
            setFontSize,
            setTheme,
            setTextWidth,
            setFont,
            setLineHeight,
            setLetterSpacing,
            setParaIndent,
            setTextAlign,
            setIndent,
            toggleSettings,
            showSettingsTab,
            updateSettingsUI,
            setDimmer,
            applySettings,
            restoreSettings
        };
    }

    root.createSettingsUiManager = createSettingsUiManager;
})(window);
