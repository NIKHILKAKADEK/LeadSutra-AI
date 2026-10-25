import { motion } from 'framer-motion'
import { ArrowRight, BarChart3, Compass, Layers3, Sparkles, Target, Workflow } from 'lucide-react'
import { Link } from 'react-router-dom'

const features = [
  { icon: Compass, title: 'Discover the right businesses', copy: 'Find local prospects and turn public business details into a usable lead list.' },
  { icon: Sparkles, title: 'Enrich with useful context', copy: 'Bring websites, contact details, and grounded research together in one workspace.' },
  { icon: Target, title: 'Prioritize your next move', copy: 'Use consistent lead scoring to focus attention where it can make a difference.' },
]

export function LandingPage() {
  return <main className="landing-page">
    <div className="landing-glow landing-glow-one" aria-hidden="true" />
    <div className="landing-glow landing-glow-two" aria-hidden="true" />
    <header className="landing-nav">
      <Link to="/" className="landing-brand"><span className="brand-mark"><Sparkles size={17}/></span><span className="brand-name">leadsutra<span>AI</span></span></Link>
      <nav aria-label="Main navigation"><a href="#features">Platform</a><a href="#workflow">How it works</a><Link className="landing-login" to="/login">Sign in</Link><Link className="landing-signup" to="/signup">Get started <ArrowRight size={15}/></Link></nav>
    </header>

    <section className="landing-hero">
      <motion.div className="landing-copy" initial={{ opacity: 0, y: 22 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6 }}>
        <span className="landing-kicker"><span /> AI-POWERED SALES DEVELOPMENT</span>
        <h1>Turn business discovery into <em>real momentum.</em></h1>
        <p>Find promising businesses, understand what they need, and move your sales work forward from one focused workspace.</p>
        <div className="landing-cta"><Link className="landing-signup landing-primary-cta" to="/signup">Build your pipeline <ArrowRight size={17}/></Link><a className="landing-secondary-cta" href="#workflow">Explore the workflow <span>↓</span></a></div>
        <div className="landing-proof"><div className="landing-proof-icon"><LockKeyholeIcon /></div><span>Private by default <b>·</b> Your workspace data stays yours</span></div>
      </motion.div>
      <motion.div className="landing-visual" initial={{ opacity: 0, scale: .96, y: 18 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={{ duration: .65, delay: .12 }}>
        <div className="landing-window">
          <div className="landing-window-top"><div className="window-dots"><i/><i/><i/></div><span>ILLUSTRATIVE PREVIEW</span><span className="window-status">● SAMPLE</span></div>
          <div className="landing-window-body">
            <div className="landing-window-title"><div><small>OVERVIEW</small><h2>Your pipeline, in focus.</h2></div><span className="window-date">This month</span></div>
            <div className="landing-stat-grid"><div className="landing-stat"><span>PROSPECTS FOUND</span><b>1,284</b><small>Across your target markets</small></div><div className="landing-stat"><span>HIGH PRIORITY</span><b>326</b><small>Ready for a closer look</small></div></div>
            <div className="landing-chart"><div className="chart-heading"><span>Discovery activity</span><small>Last 7 days</small></div><div className="chart-bars" aria-label="Illustrative activity chart">{[34, 48, 39, 62, 49, 78, 67, 91, 61, 82, 72, 100].map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}</div><div className="chart-labels"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span></div></div>
            <div className="landing-activity"><span className="activity-icon"><BarChart3 size={16}/></span><div><b>New opportunities, organized</b><small>Discovery, research, and scoring connected.</small></div><ArrowRight size={16}/></div>
          </div>
        </div>
        <motion.div className="landing-float-card" animate={{ y: [0, -8, 0] }} transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}><span><Layers3 size={17}/></span><div><b>One connected workflow</b><small>From discovery to decision</small></div></motion.div>
      </motion.div>
    </section>

    <section className="landing-features" id="features">
      <div className="landing-section-intro"><span className="landing-kicker">A CLEARER WAY TO GROW</span><h2>Less scattered research.<br/><em>More meaningful outreach.</em></h2></div>
      <div className="landing-feature-grid">{features.map((feature, index) => <motion.article key={feature.title} className="landing-feature" initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .35 }} transition={{ duration: .45, delay: index * .08 }}><span className="feature-icon"><feature.icon size={20}/></span><h3>{feature.title}</h3><p>{feature.copy}</p></motion.article>)}</div>
    </section>

    <section className="landing-workflow" id="workflow"><span className="landing-kicker">ONE WORKFLOW, THREE STEPS</span><div className="workflow-steps"><div><b>01</b><Workflow size={20}/><h3>Discover</h3><p>Search your markets and collect business leads.</p></div><div><b>02</b><Sparkles size={20}/><h3>Understand</h3><p>Enrich each prospect with useful context.</p></div><div><b>03</b><Target size={20}/><h3>Prioritize</h3><p>Review your results and take the next step.</p></div></div></section>

    <footer className="landing-footer"><Link to="/" className="landing-brand"><span className="brand-mark"><Sparkles size={15}/></span><span className="brand-name">leadsutra<span>AI</span></span></Link><span>Make every sales conversation start with context.</span><Link to="/signup">Create your account <ArrowRight size={14}/></Link></footer>
  </main>
}

function LockKeyholeIcon() {
  return <span className="lock-mark" aria-hidden="true">✓</span>
}
