export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== 'false';

export const DEMO_USER = {
  id: 'demo-user-graphrecall',
  email: 'demo@graphrecall.ai',
  name: 'GraphRecall Demo',
  picture: '',
  settings_json: {
    sr_algorithm: 'fsrs',
    daily_limit: 18,
    notification_time: '8:30 AM',
    theme: 'Dark',
    animations: true,
  },
};
