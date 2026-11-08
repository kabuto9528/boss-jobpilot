import { createApp } from 'vue'
import { ElAlert, ElButton, ElDialog, ElDrawer, ElMenu, ElMenuItem, ElTag } from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './styles.css'

const app = createApp(App)

app.use(router)
app.use(ElAlert)
app.use(ElButton)
app.use(ElDialog)
app.use(ElDrawer)
app.use(ElMenu)
app.use(ElMenuItem)
app.use(ElTag)
app.mount('#app')
