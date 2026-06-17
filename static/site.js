/* Site-wide popover positioning + dismissal, for all popover kinds: the reflex-note bubble
   (.noted > .notepop, right edge pinned under the circled-i), the syllable etymon preview
   (.syl-w > .sylpop beside its a.syl trigger, left-anchored, opens above the syllable), and the
   morpheme-analysis label (.morph-w > .mpop, same geometry as .sylpop). On a narrow viewport either can run
   off an edge, and the sylpop can open fully above the viewport when its row sits at the top.
   CSS can't clamp them (the offset parent is a tiny inline span at an unpredictable x), so when
   one is shown we measure it and: nudge it back inside an 8px margin (translateX), and flip the
   sylpop to open BELOW its syllable when the natural position is clipped at the top (.flip, see
   site.css). Delegated on document (covers client-rendered rows in search/thesaurus) across
   hover/touch/keyboard, and deferred to the next frame so the popover — toggled via
   :hover/:focus — is actually laid out before we measure. We reset transform + .flip before each
   measure, so re-showing or resizing recomputes from the natural position: it never compounds,
   and never locks in a stale offset (the bug in the first cut: a measurement taken while the
   popover was still display:none got memoized as a useless 8px shift).
   Escape blurs the focused trigger, closing a keyboard-opened popover (WCAG 1.4.13). */
(function(){
  var M=8, pending=null, queued=false, active=null;
  /* The syllable/morpheme popovers (.sylpop/.mpop) linger 0.25s after their trigger un-hovers, so the
     pointer can travel diagonally into the bubble. That grace period meant moving quickly from one
     trigger to the next left BOTH bubbles briefly open. So when a new trigger activates we cancel the
     previous popover's transition: it then snaps to its true hover/focus state (hidden, since you've
     moved off it) at once — but stays open if it's genuinely still hovered, since we only drop the
     delay, never force visibility. The note bubble (.notepop) is display-toggled with no delay, so it
     never overlaps and needs no snapping. */
  function snapShut(wrap){
    var p=wrap&&wrap.querySelector&&wrap.querySelector('.sylpop,.mpop');
    if(!p) return;
    p.style.transition='none'; void p.offsetWidth;     // drop the close-delay -> reflect reality now
    requestAnimationFrame(function(){ p.style.transition=''; });   // restore it for this popover's next open
  }
  function fit(n){
    var p=n&&n.querySelector('.notepop,.sylpop,.mpop'); if(!p) return;
    p.style.transform='';                              // measure from the natural position
    p.classList.remove('flip');
    var r=p.getBoundingClientRect();
    if(!r.width) return;                               // not shown / laid out yet — leave it be
    if(r.top<M && (p.classList.contains('sylpop')||p.classList.contains('mpop'))){  // clipped above the viewport: open below
      p.classList.add('flip');
      r=p.getBoundingClientRect();
    }
    var w=document.documentElement.clientWidth, dx=0;
    if(r.left<M) dx=M-r.left; else if(r.right>w-M) dx=w-M-r.right;
    if(dx) p.style.transform='translateX('+Math.round(dx)+'px)';
  }
  function ping(e){
    var t=e.target, n=t&&t.closest&&t.closest('.noted,.syl-w,.morph-w');
    if(!n) return;
    if(active && active!==n) snapShut(active);   // moved to a different trigger: close the previous at once
    active=n;
    pending=n;
    if(queued) return;
    queued=true;
    requestAnimationFrame(function(){ queued=false; fit(pending); });
  }
  ['pointerover','pointerdown','focusin'].forEach(function(ev){
    document.addEventListener(ev, ping, true);
  });
  window.addEventListener('resize', function(){ if(pending) fit(pending); }, {passive:true});
  document.addEventListener('keydown', function(e){
    if(e.key!=='Escape') return;
    var a=document.activeElement;
    if(a && a.closest && a.closest('.noted,.syl-w,.morph-w')) a.blur();
  });
})();
