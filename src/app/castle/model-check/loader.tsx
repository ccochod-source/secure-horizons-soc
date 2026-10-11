'use client';
import dynamic from 'next/dynamic';

export const ModelCheckLoader = dynamic(() => import('./model-check').then((m) => m.ModelCheck), { ssr: false });
