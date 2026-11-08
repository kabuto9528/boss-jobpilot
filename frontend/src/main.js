import { createApp } from 'vue'
import { ElAlert, ElButton, ElMenu, ElMenuItem, ElTag } from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './styles.css'

const app = createApp(App)

app.use(router)
app.use(ElAlert)
app.use(ElButton)
app.use(ElMenu)
app.use(ElMenuItem)
app.use(ElTag)
app.mount('#app')
