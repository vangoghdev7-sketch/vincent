'use client';

/**
 * Shared framer-motion entry — LazyMotion + domAnimation keeps the animation
 * feature set small instead of pulling the full motion bundle into every panel.
 *
 * Import `motion` / `AnimatePresence` from here (not `framer-motion`) so the
 * app stays on the lightweight `m` component under LazyMotion.
 */
import type { ReactNode } from 'react';
import {
  LazyMotion,
  domAnimation,
  m,
  AnimatePresence,
} from 'framer-motion';

export { LazyMotion, domAnimation, AnimatePresence };
export const motion = m;

export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      {children}
    </LazyMotion>
  );
}

// PRO MAX UI/UX Framer Motion Variants

export const fadeIn = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.3, ease: 'easeOut' } }
};

export const slideUp = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } }
};

export const staggerContainer = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1
    }
  }
};
