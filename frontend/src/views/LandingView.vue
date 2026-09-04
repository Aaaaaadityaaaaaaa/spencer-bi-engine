<template>
  <div style="--primary-5: #83bfc8;" class="min-h-screen relative bg-[#000000] text-white font-['Inter',_sans-serif] selection:bg-primary-5/30 selection:text-primary-5 overflow-x-hidden" @scroll="handleScroll" ref="scrollContainer">
    
    <!-- 21st.dev Style Animated Grid Background -->
    <div class="fixed inset-0 z-0 pointer-events-none bg-[#050505] overflow-hidden">
      <div class="absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]">
        <div class="absolute inset-[-100%] bg-[linear-gradient(to_right,#333_1px,transparent_1px),linear-gradient(to_bottom,#333_1px,transparent_1px)] bg-[size:40px_40px] animate-grid-flow opacity-30"></div>
      </div>
      <!-- Subtle atmospheric glows -->
      <div class="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-primary-5/15 rounded-full blur-[120px] mix-blend-screen"></div>
      <div class="absolute bottom-0 left-1/4 w-[500px] h-[300px] bg-[#7c3aed]/10 rounded-full blur-[100px] mix-blend-screen"></div>
    </div>

    <!-- Sticky Minimal Navbar -->
    <nav :class="['fixed top-0 w-full z-50 transition-all duration-300', scrolled ? 'bg-[#000000]/80 backdrop-blur-md border-b border-zinc-800' : 'bg-transparent border-transparent']">
      <div class="max-w-[1440px] mx-auto px-6 h-16 flex justify-between items-center">
        <!-- Logo -->
        <div class="text-xl font-bold text-white tracking-tight flex items-center gap-1">
          Spencer<span class="text-primary-5">·</span>
        </div>
        
        <!-- Links -->
        <div class="hidden md:flex gap-8 items-center">
          <a href="#features" class="text-sm font-medium text-zinc-500 hover:text-white transition-colors">Features</a>
          <a href="#how-it-works" class="text-sm font-medium text-zinc-500 hover:text-white transition-colors">How It Works</a>
          <a href="#security" class="text-sm font-medium text-zinc-500 hover:text-white transition-colors">Security</a>
          <a href="#pricing" class="text-sm font-medium text-zinc-500 hover:text-white transition-colors">Pricing</a>
        </div>
        
        <!-- CTA -->
        <router-link
          to="/login"
          class="bg-primary-5 text-[#09090b] text-sm font-bold px-4 py-2 rounded-2 hover:bg-primary-5/90 transition-all hover:shadow-[0_0_15px_rgba(131,191,200,0.4)]"
        >
          Get Started Free →
        </router-link>
      </div>
    </nav>

    <!-- Main Content Area -->
    <main class="relative z-10 pt-32 pb-24">
      
      <!-- Section 1: Hero -->
      <section class="flex flex-col items-center justify-center px-6 pt-10 pb-20 max-w-[800px] mx-auto text-center">
        <!-- Pill Badge -->
        <div class="inline-block px-3 py-1 mb-8 border border-primary-5/30 bg-primary-5/10 rounded-full animate-hero-reveal opacity-0" style="animation-delay: 0ms; animation-fill-mode: forwards;">
          <span class="text-xs font-semibold text-primary-5 uppercase tracking-widest">
            ✦ AI-Powered Analytics
          </span>
        </div>
        
        <!-- Headline -->
        <h1 class="text-5xl md:text-[72px] font-bold tracking-tight text-white leading-[1.1] mb-6 animate-hero-reveal opacity-0" style="animation-delay: 200ms; animation-fill-mode: forwards;">
          Query in English.<br>Visualize Instantly.
        </h1>
        
        <!-- Subheadline -->
        <p class="text-lg md:text-xl text-zinc-400 leading-relaxed max-w-[560px] mx-auto animate-hero-reveal opacity-0 font-medium" style="animation-delay: 400ms; animation-fill-mode: forwards;">
          Spencer is an AI-first business intelligence engine that turns raw CSV and Parquet files into interactive dashboards, cleaned datasets, and natural-language SQL queries — all locally, in seconds, with zero infrastructure.
        </p>
        
        <!-- CTAs -->
        <div class="flex flex-wrap justify-center gap-6 mt-10 animate-hero-reveal opacity-0" style="animation-delay: 600ms; animation-fill-mode: forwards;">
          <router-link
            to="/table"
            class="bg-primary-5 text-[#09090b] text-base font-bold px-6 py-3 rounded-2 hover:bg-primary-5/90 transition-all shadow-[0_0_20px_rgba(131,191,200,0.2)] hover:shadow-[0_0_30px_rgba(131,191,200,0.4)]"
          >
            Start Analyzing →
          </router-link>
          <button class="bg-[#09090b] border border-zinc-700 text-white text-base font-semibold px-6 py-3 rounded-2 hover:bg-zinc-800 hover:border-zinc-600 transition-all">
            Watch Demo
          </button>
        </div>
      </section>

      <!-- Hero Mockup -->
      <section class="max-w-[1100px] mx-auto px-6 mb-32 relative perspective-mockup group animate-hero-reveal opacity-0" style="animation-delay: 1000ms; animation-fill-mode: forwards;">
        <!-- Glow under mockup -->
        <div class="absolute inset-x-10 bottom-0 top-20 bg-primary-5/20 blur-[80px] -z-10 group-hover:bg-primary-5/30 transition-all duration-700"></div>
        
        <!-- The Glass Browser Frame -->
        <div class="w-full aspect-[16/9] bg-[#09090b]/80 backdrop-blur-[25px] border border-zinc-800 rounded-3 overflow-hidden flex flex-col shadow-[0_40px_120px_-20px_rgba(131,191,200,0.2)] transform rotate-x-[2deg] animate-float">
          
          <!-- Mockup Header -->
          <div class="h-10 border-b border-zinc-800 bg-[#18181b]/70 flex items-center px-4 gap-2">
            <div class="w-3 h-3 rounded-full bg-[#3f3f46]"></div>
            <div class="w-3 h-3 rounded-full bg-[#3f3f46]"></div>
            <div class="w-3 h-3 rounded-full bg-[#3f3f46]"></div>
          </div>
          
          <!-- Mockup Content (Fake Dashboard) -->
          <div class="flex-1 flex bg-[#050505]">
            <!-- Sidebar -->
            <div class="w-48 border-r border-zinc-800 p-4 flex flex-col gap-4">
              <div class="h-6 w-24 bg-[#18181b] rounded border border-zinc-800"></div>
              <div class="h-4 w-16 bg-[#18181b] rounded mt-4"></div>
              <div class="h-4 w-20 bg-[#18181b] rounded"></div>
              <div class="h-4 w-24 bg-[#18181b] rounded"></div>
            </div>
            <!-- Main Canvas -->
            <div class="flex-1 p-6 flex flex-col gap-4 relative overflow-hidden bg-[radial-gradient(#27272a_1px,transparent_1px)] [background-size:20px_20px] opacity-90">
              <div class="flex gap-4">
                <div class="flex-1 bg-[#18181b] border border-zinc-800 rounded-2 p-4 h-24 shadow-md">
                  <div class="text-xs text-zinc-400 font-['JetBrains_Mono'] mb-1">TOTAL REVENUE</div>
                  <div class="text-2xl font-['JetBrains_Mono'] font-bold text-white">$1,204,500</div>
                </div>
                <div class="flex-1 bg-[#18181b] border border-zinc-800 rounded-2 p-4 h-24 shadow-md">
                  <div class="text-xs text-zinc-400 font-['JetBrains_Mono'] mb-1">ACTIVE USERS</div>
                  <div class="text-2xl font-['JetBrains_Mono'] font-bold text-white">12,491</div>
                </div>
              </div>
              <div class="flex-1 bg-[#18181b] border border-zinc-800 rounded-2 p-4 flex items-end gap-3 pt-12 shadow-md">
                 <!-- Fake Chart Bars -->
                 <div class="flex-1 bg-primary-5/40 hover:bg-primary-5 transition-colors rounded-t h-[40%]"></div>
                 <div class="flex-1 bg-primary-5/60 hover:bg-primary-5 transition-colors rounded-t h-[75%]"></div>
                 <div class="flex-1 bg-primary-5/80 hover:bg-primary-5 transition-colors rounded-t h-[95%]"></div>
                 <div class="flex-1 bg-primary-5/50 hover:bg-primary-5 transition-colors rounded-t h-[60%]"></div>
                 <div class="flex-1 bg-primary-5/30 hover:bg-primary-5 transition-colors rounded-t h-[30%]"></div>
                 <div class="flex-1 bg-primary-5 hover:bg-primary-5 transition-colors rounded-t h-[100%] shadow-[0_0_15px_rgba(131,191,200,0.5)]"></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Trust Bar -->
      <section class="bg-[#050505] py-8 mb-32 border-y border-zinc-800 reveal-on-scroll">
        <div class="max-w-[1200px] mx-auto px-6 text-center">
          <p class="text-xs font-bold text-zinc-400 tracking-[0.1em] uppercase mb-8">Trusted by Data Teams Worldwide</p>
          <div class="flex flex-wrap justify-center items-center gap-12 md:gap-24 opacity-50">
             <!-- Abstract Geometric Logos -->
             <div class="w-8 h-8 bg-zinc-600 rounded-full reveal-stagger"></div>
             <div class="w-8 h-8 bg-zinc-600 rounded-sm rotate-45 reveal-stagger"></div>
             <div class="w-10 h-6 bg-zinc-600 rounded-full reveal-stagger"></div>
             <div class="w-0 h-0 border-l-[16px] border-r-[16px] border-b-[28px] border-l-transparent border-r-transparent border-b-ink-gray-5 reveal-stagger"></div>
             <div class="w-8 h-8 bg-transparent border-[6px] border-zinc-600 rounded-full reveal-stagger"></div>
          </div>
        </div>
      </section>

      <!-- Capabilities Grid -->
      <section id="features" class="max-w-[1200px] mx-auto px-6 mb-40">
        <div class="text-center mb-16 reveal-on-scroll">
          <p class="text-[14px] font-bold text-primary-5 tracking-[0.08em] uppercase mb-4">Capabilities</p>
          <h2 class="text-[44px] font-bold text-white leading-tight mb-4 tracking-tight">Everything you need. Nothing you don't.</h2>
          <p class="text-lg text-zinc-400 font-medium">From raw files to executive dashboards in minutes — not months.</p>
        </div>
        
        <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div class="bg-[#09090b] border border-zinc-800 rounded-3 p-8 hover:border-zinc-600 hover:-translate-y-1 transition-all duration-300 shadow-sm hover:shadow-lg reveal-on-scroll">
            <div class="text-primary-5 mb-6 bg-primary-5/10 w-12 h-12 rounded-full flex items-center justify-center border border-primary-5/20"><span class="material-symbols-outlined text-[24px]">chat_spark</span></div>
            <h3 class="text-white font-bold mb-3 text-xl">Ask in English, Execute in SQL</h3>
            <p class="text-[15px] text-zinc-400 leading-relaxed font-medium">Type business questions in plain English. Spencer's AI writes production-grade DuckDB SQL, explains it, and lets you approve before executing. With a self-correcting 3-step retry loop, it handles edge cases automatically.</p>
          </div>
          
          <div class="bg-[#09090b] border border-zinc-800 rounded-3 p-8 hover:border-zinc-600 hover:-translate-y-1 transition-all duration-300 shadow-sm hover:shadow-lg reveal-on-scroll">
            <div class="text-primary-5 mb-6 bg-primary-5/10 w-12 h-12 rounded-full flex items-center justify-center border border-primary-5/20"><span class="material-symbols-outlined text-[24px]">grid_view</span></div>
            <h3 class="text-white font-bold mb-3 text-xl">Drag-and-Drop Dashboards</h3>
            <p class="text-[15px] text-zinc-400 leading-relaxed font-medium">Build interactive dashboards with 12+ chart types — bar, line, scatter, heatmap, treemap, funnel, box plot, and more. Drag, resize, and style every element. Add KPI cards and slicers for real-time filtering.</p>
          </div>
          
          <div class="bg-[#09090b] border border-zinc-800 rounded-3 p-8 hover:border-zinc-600 hover:-translate-y-1 transition-all duration-300 shadow-sm hover:shadow-lg reveal-on-scroll">
            <div class="text-primary-5 mb-6 bg-primary-5/10 w-12 h-12 rounded-full flex items-center justify-center border border-primary-5/20"><span class="material-symbols-outlined text-[24px]">auto_fix</span></div>
            <h3 class="text-white font-bold mb-3 text-xl">Visual Data Cleaning</h3>
            <p class="text-[15px] text-zinc-400 leading-relaxed font-medium">16+ one-click transform operations — deduplicate, impute nulls, normalize strings, extract dates, bin values, flag outliers, and more. Preview every change before applying. Undo anything with 10-step snapshot history.</p>
          </div>
          
          <div class="bg-[#09090b] border border-zinc-800 rounded-3 p-8 hover:border-zinc-600 hover:-translate-y-1 transition-all duration-300 shadow-sm hover:shadow-lg reveal-on-scroll">
            <div class="text-primary-5 mb-6 bg-primary-5/10 w-12 h-12 rounded-full flex items-center justify-center border border-primary-5/20"><span class="material-symbols-outlined text-[24px]">cloud_off</span></div>
            <h3 class="text-white font-bold mb-3 text-xl">Zero Infrastructure</h3>
            <p class="text-[15px] text-zinc-400 leading-relaxed font-medium">No database setup. No cloud warehouse. No ETL pipelines. Upload a CSV or Parquet file and start querying in under 3 seconds. Spencer runs a vectorized DuckDB engine locally.</p>
          </div>
          
          <div id="security" class="bg-[#09090b] border border-zinc-800 rounded-3 p-8 hover:border-zinc-600 hover:-translate-y-1 transition-all duration-300 shadow-sm hover:shadow-lg reveal-on-scroll">
            <div class="text-primary-5 mb-6 bg-primary-5/10 w-12 h-12 rounded-full flex items-center justify-center border border-primary-5/20"><span class="material-symbols-outlined text-[24px]">shield_lock</span></div>
            <h3 class="text-white font-bold mb-3 text-xl">Enterprise-Grade Security</h3>
            <p class="text-[15px] text-zinc-400 leading-relaxed font-medium">Triple-layer SQL sandboxing — AST validation via sqlglot, tenant-scoped table isolation, and transactional rollback containment. 25/25 adversarial injection tests passed. Every AI query requires human approval.</p>
          </div>
          
          <div class="bg-[#09090b] border border-zinc-800 rounded-3 p-8 hover:border-zinc-600 hover:-translate-y-1 transition-all duration-300 shadow-sm hover:shadow-lg reveal-on-scroll">
            <div class="text-primary-5 mb-6 bg-primary-5/10 w-12 h-12 rounded-full flex items-center justify-center border border-primary-5/20"><span class="material-symbols-outlined text-[24px]">link</span></div>
            <h3 class="text-white font-bold mb-3 text-xl">Smart Data Modeling</h3>
            <p class="text-[15px] text-zinc-400 leading-relaxed font-medium">Auto-suggested joins across your uploaded tables based on column name and type analysis. Virtual query-time relationships — zero data duplication, zero materialized merges.</p>
          </div>
        </div>
      </section>

      <!-- How It Works (Visual Pipeline) -->
      <section id="how-it-works" class="max-w-[1000px] mx-auto px-6 mb-40 reveal-on-scroll">
        <div class="text-center mb-20">
          <p class="text-[14px] font-bold text-primary-5 tracking-[0.08em] uppercase mb-4">How It Works</p>
          <h2 class="text-[44px] font-bold text-white leading-tight">From file to insight in three steps.</h2>
        </div>
        
        <div class="relative flex flex-col md:flex-row justify-between gap-12 md:gap-4">
          <!-- Animated Connecting Line (Hidden on Mobile) -->
          <div class="absolute top-8 left-[10%] right-[10%] h-[2px] hidden md:block z-0 opacity-40">
            <svg width="100%" height="100%" preserveAspectRatio="none">
              <line x1="0" y1="0" x2="100%" y2="0" stroke="#83bfc8" stroke-width="2" stroke-dasharray="10 10" class="animate-flow"></line>
            </svg>
          </div>
          
          <div class="flex-1 flex flex-col relative z-10 p-2 items-center md:items-start text-center md:text-left">
            <div class="w-16 h-16 rounded-full bg-primary-5 text-[#09090b] flex items-center justify-center font-bold text-2xl mb-6 shadow-[0_0_20px_rgba(131,191,200,0.3)] border-4 border-[#000000]">1</div>
            <h3 class="text-[20px] font-bold text-white mb-2">Upload</h3>
            <p class="text-zinc-400 font-medium">Drop your CSV or Parquet file. Spencer auto-detects schemas, types, and data quality issues.</p>
          </div>
          
          <div class="flex-1 flex flex-col relative z-10 p-2 items-center md:items-start text-center md:text-left">
            <div class="w-16 h-16 rounded-full bg-primary-5 text-[#09090b] flex items-center justify-center font-bold text-2xl mb-6 shadow-[0_0_20px_rgba(131,191,200,0.3)] border-4 border-[#000000]">2</div>
            <h3 class="text-[20px] font-bold text-white mb-2">Ask</h3>
            <p class="text-zinc-400 font-medium">Type a question in English or write SQL directly. The AI generates, explains, and self-corrects queries for you.</p>
          </div>
          
          <div class="flex-1 flex flex-col relative z-10 p-2 items-center md:items-start text-center md:text-left">
            <div class="w-16 h-16 rounded-full bg-primary-5 text-[#09090b] flex items-center justify-center font-bold text-2xl mb-6 shadow-[0_0_20px_rgba(131,191,200,0.3)] border-4 border-[#000000]">3</div>
            <h3 class="text-[20px] font-bold text-white mb-2">Visualize</h3>
            <p class="text-zinc-400 font-medium">Drag results onto the canvas. Build charts, KPI cards, and filterable dashboards — then export or share.</p>
          </div>
        </div>
      </section>

      <!-- By The Numbers -->
      <section class="bg-[#050505] py-24 mb-40 relative reveal-on-scroll overflow-hidden border-y border-zinc-800">
        <!-- Radial Glow -->
        <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div class="w-[600px] h-[300px] bg-primary-5/10 blur-[100px] rounded-[100%]"></div>
        </div>
        
        <div class="max-w-[1000px] mx-auto px-6 relative z-10 grid grid-cols-2 md:grid-cols-4 gap-12 text-center">
          <div>
            <div class="font-['JetBrains_Mono'] text-[48px] font-bold text-white mb-2 count-up" data-val="10">0M+</div>
            <div class="text-zinc-400 font-medium text-sm">Rows processed locally</div>
          </div>
          <div>
            <div class="font-['JetBrains_Mono'] text-[48px] font-bold text-white mb-2 count-up" data-val="12">0+</div>
            <div class="text-zinc-400 font-medium text-sm">Chart types built in</div>
          </div>
          <div>
            <div class="font-['JetBrains_Mono'] text-[48px] font-bold text-white mb-2 count-up" data-val="2">&lt;0s</div>
            <div class="text-zinc-400 font-medium text-sm">Avg query generation</div>
          </div>
          <div>
            <div class="font-['JetBrains_Mono'] text-[48px] font-bold text-white mb-2 count-up" data-val="100">0%</div>
            <div class="text-zinc-400 font-medium text-sm">SQL injection tests passed</div>
          </div>
        </div>
      </section>

      <!-- Final CTA -->
      <section class="max-w-[800px] mx-auto px-6 text-center py-20 relative reveal-on-scroll mb-10">
        <!-- Pulsing Glow Behind CTA -->
        <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div class="w-[400px] h-[200px] bg-primary-5 opacity-20 blur-[100px] animate-pulse-slow"></div>
        </div>
        
        <h2 class="text-[48px] font-bold text-white mb-6 relative z-10 tracking-tight">Your data deserves better tools.</h2>
        <p class="text-lg text-zinc-400 font-medium mb-12 relative z-10">Start building dashboards in seconds. No credit card. No database. No friction.</p>
        <router-link
          to="/login"
          class="inline-block bg-primary-5 text-[#09090b] text-lg font-bold px-10 py-4 rounded-3 hover:bg-primary-5/90 transition-all shadow-[0_0_30px_rgba(131,191,200,0.3)] hover:shadow-[0_0_40px_rgba(131,191,200,0.5)] hover:-translate-y-1 relative z-10"
        >
          Get Started Free →
        </router-link>
        <p class="text-[13px] text-zinc-500 font-medium mt-6 relative z-10">Free forever for individual analysts</p>
      </section>
      
    </main>

    <!-- Minimal Footer -->
    <footer class="bg-[#09090b] border-t border-zinc-800 py-10 relative z-10">
      <div class="max-w-[1440px] mx-auto px-6 flex flex-col md:flex-row justify-between items-center gap-6">
        <div class="text-zinc-500 text-sm font-medium">© 2026 Spencer</div>
        <div class="flex gap-8 text-sm text-zinc-500 font-medium">
          <a href="#" class="hover:text-white transition-colors">Privacy</a>
          <a href="#" class="hover:text-white transition-colors">Terms</a>
          <a href="#" class="hover:text-white transition-colors">GitHub</a>
          <a href="#" class="hover:text-white transition-colors">Docs</a>
        </div>
        <div class="flex gap-4 text-zinc-500">
          <a href="#" class="hover:text-white transition-colors"><span class="material-symbols-outlined text-[20px]">share</span></a>
          <a href="#" class="hover:text-white transition-colors"><span class="material-symbols-outlined text-[20px]">code</span></a>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const scrolled = ref(false)
let observer: IntersectionObserver | null = null

function handleScroll() {
  scrolled.value = window.scrollY > 20
}

onMounted(() => {
  document.body.style.backgroundColor = '#000000'
  window.addEventListener('scroll', handleScroll)
  
  observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible')
        
        if (entry.target.classList.contains('count-up')) {
          const el = entry.target as HTMLElement
          const target = parseInt(el.getAttribute('data-val') || '0', 10)
          let current = 0
          const suffix = el.innerText.replace(/[0-9<]/g, '')
          const prefix = el.innerText.includes('<') ? '<' : ''
          
          const interval = setInterval(() => {
            current += Math.ceil(target / 20)
            if (current >= target) {
              current = target
              clearInterval(interval)
            }
            el.innerText = `${prefix}${current}${suffix}`
          }, 40)
        }
        
        if (entry.target.classList.contains('reveal-stagger-parent')) {
           const children = entry.target.querySelectorAll('.reveal-stagger')
           children.forEach((child, index) => {
             setTimeout(() => {
               child.classList.add('visible')
             }, index * 100)
           })
        }
        
        observer?.unobserve(entry.target)
      }
    })
  }, { threshold: 0.2 })

  document.querySelectorAll('.reveal-on-scroll, .count-up').forEach(el => observer?.observe(el))
  
  const trustBar = document.querySelector('.opacity-50.flex-wrap')
  if (trustBar) {
    trustBar.classList.add('reveal-stagger-parent')
    observer.observe(trustBar)
  }
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
  if (observer) observer.disconnect(); document.body.style.backgroundColor = ''
})
</script>

<style scoped>
@keyframes hero-reveal {
  0% { opacity: 0; transform: translateY(30px); }
  100% { opacity: 1; transform: translateY(0); }
}
.animate-hero-reveal {
  animation-name: hero-reveal;
  animation-duration: 800ms;
  animation-timing-function: cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes float {
  0%, 100% { transform: perspective(1000px) rotateX(2deg) translateY(0px); }
  50% { transform: perspective(1000px) rotateX(2deg) translateY(-6px); }
}
.animate-float {
  animation: float 6s infinite ease-in-out;
}
.perspective-mockup {
  perspective: 1000px;
}

.reveal-on-scroll {
  opacity: 0;
  transform: translateY(40px);
  transition: all 800ms cubic-bezier(0.16, 1, 0.3, 1);
}
.reveal-on-scroll.visible {
  opacity: 1;
  transform: translateY(0);
}

.reveal-stagger {
  opacity: 0;
  transition: opacity 400ms ease;
}
.reveal-stagger.visible {
  opacity: 1;
}

@keyframes dash-flow {
  to { stroke-dashoffset: -20; }
}
.animate-flow {
  animation: dash-flow 2s linear infinite;
}

@keyframes pulse-slow {
  0%, 100% { opacity: 0.15; }
  50% { opacity: 0.3; }
}
.animate-pulse-slow {
  animation: pulse-slow 4s infinite ease-in-out;
}

@keyframes grid-flow {
  0% { transform: translateY(0); }
  100% { transform: translateY(40px); } /* exactly one background-size block */
}
.animate-grid-flow {
  animation: grid-flow 2s linear infinite;
}
</style>
