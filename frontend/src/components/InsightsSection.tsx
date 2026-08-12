import { motion } from 'framer-motion'
import { BlurIn } from './BlurIn'

const cards = [
  {
    video: 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_143605_bc7bd6c0-9c68-49ff-a9d3-073a10759fa4.mp4',
    overlay: 'bg-[rgba(206,223,235,0.25)]',
    stat: '1.6M',
    description: 'Active members rely on us for effortless payment experiences',
    maxWidth: 'max-w-[377px]',
    height: 'min-h-[450px]',
  },
  {
    video: 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_145119_f4ec4d9f-3ecd-4116-baa3-26e8cf2df976.mp4',
    overlay: 'bg-[rgba(247,236,233,0.6)]',
    stat: '850K',
    description: 'Transfers completed each day, quick and protected',
    maxWidth: 'max-w-[351px]',
    height: 'min-h-[350px]',
  },
  {
    video: 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260405_140728_ae719193-f10b-4105-82fc-c989610b3aa6.mp4',
    overlay: 'bg-[rgba(218,218,218,0.2)]',
    stat: '120+',
    description: 'Nations enabled for instant checkouts and worldwide remittance',
    maxWidth: 'max-w-[351px]',
    height: 'min-h-[450px]',
  },
]

const rowVariants = { hidden: { opacity: 0 }, visible: { opacity: 1, transition: { staggerChildren: 0.2 } } }
const cardVariants = { hidden: { opacity: 0, y: 30 }, visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: 'easeOut' as const } } }

export function InsightsSection() {
  return (
    <section className="flex min-h-screen flex-col gap-[90px] bg-white px-6 py-20 text-[#00041F] md:px-12 lg:px-[60px]">
      <div className="flex max-w-[517px] flex-col gap-10">
        <BlurIn>
          <h1 className="font-helvetica-neue text-4xl font-medium leading-[1] tracking-[-0.03em] md:text-5xl lg:text-6xl lg:leading-[60px]">Instant payment clarity counts</h1>
        </BlurIn>
        <p className="max-w-[361px] font-helvetica-neue text-base text-[#49484F] md:text-lg lg:text-xl">Real-time data powers smarter spending choices every day</p>
      </div>
      <motion.div className="flex flex-col items-stretch gap-5 lg:flex-row lg:items-end" variants={rowVariants} initial="hidden" whileInView="visible" viewport={{ once: true, amount: 0.2 }}>
        {cards.map((card) => (
          <motion.article className={`relative flex flex-1 flex-col justify-end overflow-hidden rounded-[40px] p-10 ${card.height}`} variants={cardVariants} key={card.stat}>
            <video autoPlay loop muted playsInline className="absolute inset-0 h-full w-full object-cover" aria-hidden="true">
              <source src={card.video} type="video/mp4" />
            </video>
            <div className={`absolute inset-0 ${card.overlay}`} />
            <div className="relative z-10 flex max-w-[388px] flex-col gap-5">
              <p className="font-helvetica-neue text-5xl font-medium leading-[1] tracking-[-0.03em] text-[#00041F] md:text-[60px] md:leading-[60px]">{card.stat}</p>
              <p className={`font-helvetica-neue text-lg tracking-[-0.02em] text-[#49484F] opacity-80 md:text-[22px] ${card.maxWidth}`}>{card.description}</p>
            </div>
          </motion.article>
        ))}
      </motion.div>
    </section>
  )
}
