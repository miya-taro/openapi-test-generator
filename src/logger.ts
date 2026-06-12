import pino from 'pino'

let logger = pino({ level: 'info' })

export function setLogLevel(level: string): void {
  logger = pino({ level })
}

export { logger }
