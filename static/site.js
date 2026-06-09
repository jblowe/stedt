/* Site-wide note-popover positioning. A popover's right edge is pinned to its circled-i
   (see .noted in site.css), so on a narrow viewport a wide bubble can run off the left edge.
   CSS can't clamp it to the viewport (the bubble's offset parent is a tiny inline span at an
   unpredictable x), so when a note is shown we measure it and, if it overflows, nudge it back
   inside an 8px margin. Delegated on document (covers client-rendered notes in search/thesaurus)
   across hover/touch/keyboard, and deferred to the next frame so the popover — toggled via
   :hover/:focus — is actually laid out before we measure. We reset the transform before each
   measure, so re-showing or resizing recomputes from the natural position: it never compounds,
   and never locks in a stale offset (the bug in the first cut: a measurement taken while the
   popover was still display:none got memoized as a useless 8px shift). */
(function(){
  var M=8, pending=null, queued=false;
  function fit(n){
    var p=n&&n.querySelector('.notepop'); if(!p) return;
    p.style.transform='';                              // measure from the natural position
    var r=p.getBoundingClientRect();
    if(!r.width) return;                               // not shown / laid out yet — leave it be
    var w=document.documentElement.clientWidth, dx=0;
    if(r.left<M) dx=M-r.left; else if(r.right>w-M) dx=w-M-r.right;
    if(dx) p.style.transform='translateX('+Math.round(dx)+'px)';
  }
  function ping(e){
    var t=e.target, n=t&&t.closest&&t.closest('.noted');
    if(!n) return;
    pending=n;
    if(queued) return;
    queued=true;
    requestAnimationFrame(function(){ queued=false; fit(pending); });
  }
  ['pointerover','pointerdown','focusin'].forEach(function(ev){
    document.addEventListener(ev, ping, true);
  });
  window.addEventListener('resize', function(){ if(pending) fit(pending); }, {passive:true});
})();
