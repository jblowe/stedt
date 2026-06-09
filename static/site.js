/* Site-wide note-popover positioning. A popover's right edge is pinned to its circled-i
   (see .noted in site.css), so on a narrow viewport a wide bubble can run off the left edge.
   CSS can't clamp it to the viewport (the bubble's offset parent is a tiny inline span at an
   unpredictable x), so on first show we measure and nudge it back inside an 8px margin.
   Delegated on document, so it also covers client-rendered notes (search, thesaurus).
   Memoized per node; reset on resize. */
(function(){
  var seen=new WeakSet(), M=8;
  function clamp(n){
    var p=n.querySelector('.notepop'); if(!p) return;
    p.style.transform='';
    var r=p.getBoundingClientRect(), w=document.documentElement.clientWidth, dx=0;
    if(r.left<M) dx=M-r.left; else if(r.right>w-M) dx=w-M-r.right;
    if(dx) p.style.transform='translateX('+Math.round(dx)+'px)';
  }
  function show(e){
    var n=e.target.closest&&e.target.closest('.noted');
    if(n&&!seen.has(n)){seen.add(n);clamp(n);}
  }
  document.addEventListener('pointerover',show,true);
  document.addEventListener('focusin',show,true);
  window.addEventListener('resize',function(){
    seen=new WeakSet();
    var ps=document.querySelectorAll('.notepop');
    for(var i=0;i<ps.length;i++) ps[i].style.transform='';
  },{passive:true});
})();
