import { Capacitor } from '@capacitor/core';

export const runtimePlatform = Capacitor.getPlatform();
export const isNativeRuntime = Capacitor.isNativePlatform();
