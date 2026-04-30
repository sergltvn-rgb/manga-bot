(function () {
  "use strict";

  const rev = window.__READER_REV || "27";
  const encodedRev = encodeURIComponent(rev);

  function loadScript(src, onload) {
    const script = document.createElement("script");
    script.src = src;
    if (onload) script.onload = onload;
    document.body.appendChild(script);
  }

  loadScript(`reader.audit.js?v=${encodedRev}`, () => {
    loadScript(`reader.js?v=${encodedRev}`);
  });
})();
